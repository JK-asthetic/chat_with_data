"""Company / account recognition — no training required.

Strategy:
  1. From the spaCy parse, pick **candidate chunks** — contiguous runs of
     PROPN (or PROPN+NOUN) that are not already labeled by the closed-set
     matcher (so EMEA, ZPA, Enterprise don't become companies). Keep
     possessive heads, drop sentence-leading verbs ("Show me ...").
  2. **Confirm** each candidate against the account list:
       - exact lookup first  (dim_account hit)
       - fuzzy via rapidfuzz (handles typos: "Siemnes" -> "Siemens AG")
  3. If `AccountLookup` is None, trust position cues only — "ARR for X"
     where X is a PROPN chunk and X is not a closed-set entity. This lets
     the extractor run in a demo without a DB connection.

AccountLookup is a protocol — in production inject
`core.companies.existing` + an in-memory list. In tests inject a stub.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Optional, Protocol

from rapidfuzz import fuzz, process
from rapidfuzz.distance import DamerauLevenshtein
from spacy.tokens import Doc, Span


# Verbs that lead imperative queries and happen to look like PROPNs when
# capitalised at sentence start.
_LEAD_VERBS = {
    "show", "give", "tell", "find", "get", "pull", "fetch", "list", "take",
    "calculate", "report", "plot", "display", "summarize", "summarise",
    "break", "rank", "run", "return", "provide", "check", "produce",
    "generate", "identify", "name", "highlight",
}

# Nouns that signal a metric → the PROPN sitting as pobj of 'for'/'of' is
# strongly a company.
_METRIC_LEMMAS = {"arr", "acv", "churn", "downsell", "growth", "revenue", "spend",
                  "renewal", "trend", "decline", "position", "total"}

# PROPN / NOUN tokens that are generic business words, never a company on
# their own. Matched against both text.lower() AND lemma, so "accounts" is
# blocked whether spaCy tags it as a lemma 'account' or leaves it as-is.
# Plain-word deep products ('Bandwidth', 'Breach', ...) — never a company name, always a product.
_PLAIN_DEEP_PRODUCTS = {"bandwidth", "breach", "breakout", "dedicated", "extranet", "promo", "zenith"}


@lru_cache(maxsize=1024)
def _looks_like_query_word(word: str) -> bool:
    """True iff `word` is a query-grammar word or one typo away from one.

    Only words of 4+ characters are checked (shorter words share too many letters by accident).
    Pool = _GENERIC_ALONE + _METRIC_LEMMAS — the same vocabulary that already breaks a chunk
    when spelled correctly. Used by the chunker to break 'HSBC totl ARR' at 'totl' as if it
    were 'total'."""
    w = word.lower()
    if len(w) < 4:
        return False
    if w in _GENERIC_ALONE or w in _METRIC_LEMMAS:
        return True
    return any(DamerauLevenshtein.distance(w, g) == 1
               for g in _GENERIC_ALONE | _METRIC_LEMMAS if abs(len(g) - len(w)) <= 1)

_GENERIC_ALONE = {
    # business words that stand in for the SUBJECT of a query, not an entity
    "net", "new", "gross", "major", "majors", "cloud", "security", "platform",
    "data", "network", "identity", "endpoint", "ai", "zero", "trust",
    # query grammar — these describe the shape of the request, never a company
    "account", "accounts", "customer", "customers", "client", "clients",
    "company", "companies", "logo", "logos", "deal", "deals",
    "geo", "geos", "geography", "geographies", "region", "regions",
    "product", "products", "segment", "segments", "sector", "sectors",
    "quarter", "quarters", "year", "years", "month", "months",
    "overall", "total", "everyone", "everybody",
    "rate", "rates", "percent", "percentage", "ratio", "share", "amount", "count", "number", "numbers",
    "breakdown", "split", "contribution", "profile", "performance", "summary", "detail", "details",
    "difference", "comparison", "change", "changes", "increase", "decrease", "value", "values",
} | _PLAIN_DEEP_PRODUCTS

# The vendor is never its own customer. "ARR for Zscaler" means total ARR,
# not an account filter. Keep this tight — only the vendor name + obvious
# abbreviations; adding more here hides real accounts.
_VENDOR_SELF = {"zscaler", "zs"}


_CHAIN_GAP_RE = re.compile(r"^\s*(?:,\s*)?(?:and|or|vs\.?|versus|,)\s*$", re.I)


def _chain_gap(text: str, start: int, end: int) -> bool:
    """True iff the characters between two adjacent candidates form a list
    connector — ',', 'and', 'or', 'vs'. Used to accept 'B' in 'A and B'."""
    return bool(_CHAIN_GAP_RE.match(text[start:end]))


class AccountLookup(Protocol):
    """Confirms which of a set of candidate strings is a real account name."""

    def __call__(self, candidates: list[str], exact: bool = False) -> set[str]:
        """Return the subset (lowercased) that is present in `dim_account`."""
        ...


@dataclass
class Account:
    name:     str          # as typed
    canon:    str          # dim_account form if confirmed, else `name`
    start:    int          # char offset in query
    end:      int
    source:   str          # "exact" | "fuzzy" | "position"
    score:    float = 1.0  # for fuzzy matches


class AccountFinder:
    """Finds candidate companies in a Doc and (optionally) confirms them."""

    def __init__(
        self,
        lookup: Optional[AccountLookup] = None,
        known_names: Optional[list[str]] = None,
        fuzzy_threshold: int = 82,
    ):
        """`known_names` powers fuzzy matching. Pass your dim_account mirror."""
        self._lookup = lookup
        self._known = known_names or []
        self._known_lower = {n.lower(): n for n in self._known}
        self._fuzzy_threshold = fuzzy_threshold

    # ── candidate chunking ────────────────────────────────────────────────
    def _chunks(self, doc: Doc, blocked_spans: list[tuple[int, int]]) -> list[Span]:
        """Contiguous PROPN/NUM/NOUN runs that don't overlap blocked spans."""
        def in_blocked(tok) -> bool:
            return any(a <= tok.idx and tok.idx + len(tok.text) <= b for a, b in blocked_spans)

        def is_metric_word(tok) -> bool:
            return tok.lemma_.lower() in _METRIC_LEMMAS

        chunks: list[Span] = []
        i = 0
        while i < len(doc):
            t = doc[i]
            if t.pos_ not in ("PROPN", "NOUN") or t.is_stop or in_blocked(t) or is_metric_word(t):
                i += 1
                continue
            if t.i == 0 and t.lemma_.lower() in _LEAD_VERBS:
                i += 1
                continue
            j = i
            while j + 1 < len(doc):
                nxt = doc[j + 1]
                if in_blocked(nxt) or is_metric_word(nxt) or _looks_like_query_word(nxt.text):
                    break
                # Allow connectors inside names: "Bank of America", "Procter & Gamble"
                if nxt.lower_ in {"of", "the", "&", "de", "von", "van"} \
                        and j + 2 < len(doc) and doc[j + 2].pos_ in ("PROPN", "NOUN") \
                        and not in_blocked(doc[j + 2]) and not is_metric_word(doc[j + 2]):
                    j += 2
                    continue
                if nxt.pos_ in ("PROPN", "NOUN") and not nxt.is_stop:
                    j += 1
                    continue
                break
            span = doc[i:j + 1]
            text_low = span.text.lower()
            lemma_low = " ".join(t.lemma_.lower() for t in span)
            root = text_low.rstrip("s").rstrip("'")           # strip plural/possessive
            if (text_low in _GENERIC_ALONE or lemma_low in _GENERIC_ALONE
                    or text_low in _VENDOR_SELF or root in _VENDOR_SELF):
                i = j + 1
                continue
            chunks.append(span)
            i = j + 1
        return chunks

    # ── scoring ───────────────────────────────────────────────────────────
    @staticmethod
    def _position_score(span: Span, followed_by_hit: bool = False) -> float:
        """Higher = stronger signal that this chunk is a company.

        Accept threshold is 2.0. Shapes that land >= 2.0:
          * 'ARR for X'            prep='for' + metric word in sentence
          * 'X ARR'                next token is a metric
          * "X's ARR"              possessive
          * 'the account X'        account/company/customer prev
          * '... is X ARR?'        copula prev + metric next
          * 'ARR breakdown ... for X Q1FY26'   prep='for' + metric earlier
        """
        doc = span.doc
        prev = doc[span.start - 1] if span.start > 0 else None
        sent = span.sent
        s = 0.0
        has_metric_in_sent = any(t.lemma_.lower() in _METRIC_LEMMAS for t in sent)
        if prev and prev.lower_ in {"for", "of", "at", "from"} and has_metric_in_sent:
            s += 2.0                            # 'ARR for X' / 'ARR ... for X Q1FY26'
        if prev and prev.lower_ in {"account", "company", "customer", "client"}:
            s += 2.0                            # 'the account Cisco'
        if any(c.lower_ in {"'s", "’s"} for c in span.root.children):
            s += 1.5                            # "Toyota's ARR"
        nxt = doc[span.end] if span.end < len(doc) else None
        if nxt and nxt.lemma_.lower() in _METRIC_LEMMAS:
            s += 1.5                            # 'Toyota ARR' / 'HSBC ARR'
        # Copula right before the chunk — 'What is HSBC ARR?' / 'ARR was Toyota'
        if prev and prev.lemma_.lower() in {"be", "is", "are", "was", "were"}:
            s += 0.5
        if all(t.pos_ == "PROPN" for t in span):
            s += 0.5
            if followed_by_hit:
                s += 1.5                        # 'JPMorgan Private Access ARR', 'HSBC Internet Access ARR'
        return s

    # ── confirmation ──────────────────────────────────────────────────────
    def _confirm(self, cands: list[Span]) -> dict[int, tuple[str, str, float]]:
        """Returns span.start -> (canonical, source, score) for confirmed cands."""
        out: dict[int, tuple[str, str, float]] = {}
        texts = [c.text for c in cands]
        exact: set[str] = set()
        if self._lookup is not None:
            exact = {t.lower() for t in self._lookup(texts, exact=False)}
        else:
            exact = {t.lower() for t in texts if t.lower() in self._known_lower}
        for c in cands:
            if c.text.lower() in exact:
                canon = self._known_lower.get(c.text.lower(), c.text)
                out[c.start] = (canon, "exact", 1.0)
                continue
            # Don't fuzzy-confirm tokens shorter than 4 chars — too many false positives
            # (e.g. "rhe" matching "Rheem" when the user meant "the").
            if self._known and len(c.text) >= 4:
                best = process.extractOne(c.text, self._known, scorer=fuzz.WRatio)
                if best and best[1] >= self._fuzzy_threshold:
                    out[c.start] = (best[0], "fuzzy", float(best[1]) / 100.0)
        return out

    # ── public API ────────────────────────────────────────────────────────
    def find(self, doc: Doc, blocked_spans: list[tuple[int, int]]) -> list[Account]:
        cands = self._chunks(doc, blocked_spans)
        if not cands:
            return []
        confirmed = self._confirm(cands)
        text = doc.text
        hit_starts = {a for a, _ in blocked_spans}
        out: list[Account] = []
        for idx, span in enumerate(cands):
            nxt = doc[span.end] if span.end < len(doc) else None
            score = self._position_score(span, followed_by_hit=bool(nxt is not None and nxt.idx in hit_starts))
            accepted: Optional[tuple[str, str, float]] = None     # (canon, source, score)
            if span.start in confirmed:
                canon, src, cs = confirmed[span.start]
                accepted = (canon, src, cs)
            elif score >= 2.0:
                accepted = (span.text, "position", score)
            else:
                # Chaining: if the PREVIOUS candidate was accepted and the gap
                # between them is a list connector (',', 'and', 'or', 'vs'),
                # accept this one too — "Siemens and Toyota" / "A, B, and C".
                if out and _chain_gap(text, out[-1].end, span.start_char):
                    accepted = (span.text, "chain", 0.5)
            if accepted:
                canon, src, sc = accepted
                out.append(Account(span.text, canon, span.start_char, span.end_char, src, sc))

        # Deduplicate by span, keep first occurrence
        seen: set[tuple[int, int]] = set()
        deduped: list[Account] = []
        for a in out:
            key = (a.start, a.end)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(a)
        return deduped
