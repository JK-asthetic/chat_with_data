"""
Stage 0 — Rule-based decomposition (no model).

Turns one user message into a plan of self-contained sub-queries, so S1..S7 (single-intent) never change.
Every step is a dedicated, testable method, and every sub-query is built from the user's own words:

  1. References   'the second one' / 'that account' are replaced from stored result rows (core/memory.py).
  2. Clauses      the message is cut where a new ask begins ('... and what is ...', ', and the top 3 ...',
                  '; ...', a second question). 'Compare A and B', trends and 'ZIA and ZPA' are never cut,
                  because the text after 'and' does not start a new ask.
  3. Dependency   a later clause that says 'its / their' after a singular-top clause ('who is the top account')
                  becomes a dependent part and gets {{qN.account}}; after a plural list ('top 20 accounts ...
                  their ARR') it stays part of the same question.
  4. Scope        a bare clause ('and the growth') borrows account / product / region / segment / period
                  from the first clause; a clause with its own scope only borrows a missing period.
  5. Companies    a clause naming several companies ('Toyota and BMW', 'Siemens or Toyota') becomes one part
                  per company, so each is answered by the single-company pipeline.
  Over the part limit -> the message runs as one question (an unsplit question is safe).
"""
from __future__ import annotations

import re

from core.config import get_settings
from core.memory import SessionMemory
from pipeline import s1_extract_spacy as s1_extract
from pipeline.models import DecompositionPlan, SubQuery

# ── Clause boundaries ─────────────────────────────────────────────────────────

_ASK = (r"(?:what|which|who|how|show|list|give|tell|compare|break|rank|find|get|pull|take|is|are|does|did|"
        r"top|bottom|total|plot|display|calculate)")
_METRIC_ADD = r"(?:growth|churn|downsell|trend|decline|risk|acv|net[- ]new)"
_SPLIT_RE = re.compile(
    r"\?\s+(?=\S)|;\s*|[.!]\s+(?=[A-Z])"
    rf"|,\s*(?:(?:and|also)\s+)*(?:the\s+)?(?={_ASK}\b)"
    rf"|\s+(?:and|also|plus|then|additionally|as well as|along with)\s+(?:also\s+)?(?:the\s+)?(?={_ASK}\b)"
    rf"|\s+(?:and|also|plus)\s+(?:the\s+|their\s+|its\s+)?(?={_METRIC_ADD}\b)",
    re.I,
)
_ANAPHORA = re.compile(r"\b(?:its|their|them|that account|this account)\b", re.I)
_SINGULAR_ASK = re.compile(r"\bwho\s+(?:is|has)\b|\bwhich\s+(?:account|company|customer)\b", re.I)
_METRIC_WORD = re.compile(r"\b(?:arr|acv|churn|downsell|growth|decline|net[- ]new)\b", re.I)
_CONNECT = r"(?:,|\band\b|\bor\b|\bvs\.?|\bversus\b|&)"
# 'Show me top 10' / 'the bottom 5': a ranking ask that stops before saying what is ranked
_RANK_FRAGMENT = re.compile(r"^(?:\w+\s+(?:me\s+)?)?(?:the\s+)?(?:top|bottom)\s+\d+[\s.,]*$", re.I)
_RANK_PREFIX = re.compile(r"^\s*(?:the\s+)?(?:top|bottom)\s+\d+\s*", re.I)


def _spans(text: str) -> list[list[int]]:
    """[start, end] of each clause between split boundaries."""
    out, start = [], 0
    for m in _SPLIT_RE.finditer(text):
        out.append([start, m.start()])
        start = m.end()
    out.append([start, len(text)])
    out = [s for s in out if text[s[0]:s[1]].strip(" ,;")]
    # 'Total ARR in Q1, ZPA ARR in EMEA, ...': a comma between two clauses that each state their own metric
    final: list[list[int]] = []
    for a, b in out:
        cut = a
        for m in re.finditer(",", text[a:b]):
            pos = a + m.start()
            if _METRIC_WORD.search(text[cut:pos]) and _METRIC_WORD.search(text[pos + 1:b]):
                final.append([cut, pos])
                cut = pos + 1
        final.append([cut, b])
    return final


# ── Slots typed in a clause ───────────────────────────────────────────────────

def _scope_phrases(slots: dict) -> list[str]:
    """The typed scope of a clause, phrased so S1 re-reads it ('for Toyota', 'in EMEA', 'in Q1FY26')."""
    out = []
    if slots["accounts"]:
        out.append("for " + slots["accounts"][0])
    out += [f"on {p}" for p in slots["products"]]
    out += [f"in {g}" for g in slots["geo"]]
    out += [f"for {s}" for s in slots["segments"]]
    if slots["fiscal"]:
        out.append(f"in {slots['fiscal']}")
    return out


def _has_scope(slots: dict) -> bool:
    return bool(slots["accounts"] or slots["products"] or slots["geo"] or slots["segments"] or slots["fiscal"])


def _without(text: str, name: str) -> str:
    """Remove a company and the connector that joined it ('Toyota, BMW and Honda' minus BMW -> 'Toyota and Honda')."""
    n = re.escape(name)
    for pat in (rf"\s*{_CONNECT}\s*{n}(?![A-Za-z0-9])",
                rf"(?<![A-Za-z0-9]){n}\s*{_CONNECT}\s*",
                rf"(?<![A-Za-z0-9]){n}(?![A-Za-z0-9])"):
        new = re.sub(pat, " ", text, count=1, flags=re.I)
        if new != text:
            return re.sub(r"\s{2,}", " ", new).strip()
    return text


# ── Public entry point ────────────────────────────────────────────────────────

def order(subs: list[SubQuery]) -> list[list[SubQuery]] | None:
    """Group parts into waves (Kahn's algorithm): every part's dependencies sit in an earlier wave, and the
    parts inside one wave are independent of each other. None if depends_on has a cycle."""
    placed: set[str] = set()
    waves: list[list[SubQuery]] = []
    while len(placed) < len(subs):
        wave = [s for s in subs if s.id not in placed and all(d in placed for d in s.depends_on)]
        if not wave:
            return None
        waves.append(wave)
        placed |= {s.id for s in wave}
    return waves


def plan(query: str, memory: SessionMemory | None = None) -> DecompositionPlan:
    """Decompose `query` into sub-queries. Never raises: any failure degrades to a passthrough plan."""
    memory = memory or SessionMemory()
    text = " ".join(query.split())
    notes: list[str] = []
    resolved_refs = False
    if memory:
        text, ref_notes, unresolved = memory.resolve_references(text)
        notes += ref_notes
        resolved_refs = bool(ref_notes)
        if unresolved:
            return DecompositionPlan(original=query, strategy="followup", sub_queries=[], notes=notes,
                                     unresolved=unresolved)

    def passthrough(extra: str | None = None) -> DecompositionPlan:
        return DecompositionPlan(original=query, strategy="followup" if resolved_refs else "passthrough",
                                 sub_queries=[SubQuery(id="q1", text=text)], notes=notes + ([extra] if extra else []))

    # Split disabled: S0 was fragmenting single questions when it misread
    # trailing tokens ('flag', '%', 'fpr', '2027') as companies. Keep every
    # query as one part and let S1/S2 handle entity extraction holistically.
    return passthrough()


def _decompose(query: str, text: str, notes: list[str], resolved_refs: bool) -> DecompositionPlan | None:
    max_parts = get_settings().DECOMPOSER_MAX_PARTS

    # 2 + 3. clauses; a boundary is kept only where the next clause is its own question
    clauses: list[dict] = []   # {"a", "b", "dep": index of the clause it depends on}
    for a, b in _spans(text):
        clause = text[a:b].strip(" ,;")
        if not clauses:
            clauses.append({"a": a, "b": b, "dep": None})
            continue
        prev = text[clauses[-1]["a"]:clauses[-1]["b"]]
        anaphoric = _ANAPHORA.search(clause)
        if anaphoric and (_SINGULAR_ASK.search(prev) or s1_extract._SINGULAR_RE.search(prev)):
            clauses.append({"a": a, "b": b, "dep": len(clauses) - 1})     # needs the previous clause's top account
        elif anaphoric or (len(clause.split()) < 2 and not _METRIC_WORD.search(clause) and not re.search(_METRIC_ADD, clause, re.I)):
            clauses[-1]["b"] = b                                          # same question: keep the user's own words
        else:
            clauses.append({"a": a, "b": b, "dep": None})
    for c in clauses:
        t = text[c["a"]:c["b"]].strip(" ,;")
        t = t[0].upper() + t[1:]
        if re.match(r"(?:what|which|who|how)\b", t, re.I) and not t.endswith("?"):
            t += "?"
        c["text"] = t
    if len(clauses) > 1:
        notes.append(f"split into {len(clauses)} clauses at 'and <new ask>' boundaries")

    # 3b. 'top 10 and bottom 10 accounts by X in Y': the left half is only a ranking fragment, the shared tail sits in
    #     the next clause. Hand the tail back, otherwise the split leaves 'Show me top 10' with nothing to rank.
    for i, c in enumerate(clauses[:-1]):
        if c["dep"] is None and _RANK_FRAGMENT.match(c["text"]):
            for n in clauses[i + 1:]:
                m = _RANK_PREFIX.match(n["text"]) if n["dep"] is None else None
                if m and n["text"][m.end():].strip():
                    c["text"] = c["text"].rstrip(" .,;") + " " + n["text"][m.end():].strip()
                    notes.append("a ranking with no subject took the rest of the ask from the next clause")
                    break

    # 4. scope: bare clauses borrow from the first clause; a clause with its own scope only borrows a missing period
    first = s1_extract.find_slots(clauses[0]["text"])
    periods = {s["fiscal"].lower(): s["fiscal"] for s in (s1_extract.find_slots(c["text"]) for c in clauses) if s["fiscal"]}
    for idx, c in enumerate(clauses):
        if c["dep"] is not None:
            continue
        sl = s1_extract.find_slots(c["text"])
        if idx > 0 and not _has_scope(sl):
            borrowed = _scope_phrases(first)
            if borrowed:
                c["text"] = " ".join([c["text"]] + borrowed)
                notes.append(f"a clause with no scope borrowed: {', '.join(borrowed)}")
        elif not sl["fiscal"] and len(periods) == 1:   # one period typed once applies to every clause
            period = next(iter(periods.values()))
            c["text"] = c["text"].rstrip("?. ") + f" in {period}" + ("?" if c["text"].endswith("?") else "")
            notes.append(f"borrowed the shared period {period}")
        m = _METRIC_WORD.search(clauses[0]["text"])
        if idx > 0 and m and not _METRIC_WORD.search(c["text"]):
            ranked = re.search(r"\b(?:top|bottom|highest|lowest|largest|biggest)\b", c["text"], re.I)
            c["text"] = c["text"].rstrip("?. ") + (" by " if ranked else " ") + m.group(0)

    # 5. companies: one part per company named in a clause
    parts: list[SubQuery] = []
    last_part_of_clause: list[str] = []
    for c in clauses:
        body, dep_ids = c["text"], []
        if c["dep"] is not None:
            dep_id = last_part_of_clause[c["dep"]]
            body = _ANAPHORA.sub("{{" + dep_id + ".account}}", body, count=1)
            dep_ids = [dep_id]
        accounts = s1_extract.find_slots(body)["accounts"] if c["dep"] is None else []
        if len(accounts) >= 2:
            notes.append(f"{len(accounts)} companies named ({', '.join(accounts)}) — one part each")
            versions = []
            for keep in accounts:
                v = body
                for other in accounts:
                    if other != keep:
                        v = _without(v, other)
                versions.append(v)
        else:
            versions = [body]
        for v in versions:
            parts.append(SubQuery(id=f"q{len(parts) + 1}", text=v, depends_on=dep_ids))
        last_part_of_clause.append(parts[-1].id)

    if len(parts) > max_parts:
        notes.append(f"{len(parts)} parts is over the limit of {max_parts} — ran the question unchanged")
        return None
    if len(parts) == 1 and parts[0].text == text:
        return None
    strategy = "split" if len(parts) > 1 else "followup" if resolved_refs else "passthrough"
    return DecompositionPlan(original=query, strategy=strategy, sub_queries=parts, notes=notes)
