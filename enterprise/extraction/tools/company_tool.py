"""Company Tool — fuzzy company name matching on data_arr.

Search order:
  1. end_user_name  (matched entity = the end user, keyed by end_user_id)
  2. end_user_parent_name, only when nothing matched at the end-user level
     (matched entity = the parent, keyed by end_user_parent_id)

Both lists are loaded once into memory and matched with rapidfuzz.
CompanyMatch.account_id / AccountFilter.account_id hold the matched entity's id
(end_user_id or parent id, see `level`).
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional
from rapidfuzz import fuzz as _rfuzz

from pipeline.models import AccountFilter, CompanyMatch
from core.settings import get_ai
from core.db import query_all
from core.log import ok

_COMPANY_SCORE_FLOOR = 0.70
_end_users: list[dict] = []   # [{id, name, parent_id, parent_name}]
_parents: list[dict] = []     # [{id, name}]


def bootstrap_known_names() -> list[dict]:
    """End-user entries (end_user_id, end_user_name, parent) from data_arr, loaded once."""
    global _end_users
    if _end_users:
        return _end_users
    rows = query_all(
        "SELECT DISTINCT end_user_id::text AS id, end_user_name AS name, "
        "end_user_parent_id::text AS parent_id, end_user_parent_name AS parent_name "
        "FROM data_arr WHERE end_user_name IS NOT NULL AND end_user_id IS NOT NULL"
    )
    _end_users = [
        {"id": r["id"], "name": str(r["name"]), "parent_id": r.get("parent_id") or None,
         "parent_name": r.get("parent_name") or None}
        for r in rows
    ]
    ok("Company index loaded", f"{len(_end_users)} end users from data_arr (end_user_id, end_user_name)")
    return _end_users


def bootstrap_parent_names() -> list[dict]:
    """Distinct parents (end_user_parent_id, end_user_parent_name), loaded once."""
    global _parents
    if _parents:
        return _parents
    rows = query_all(
        "SELECT DISTINCT end_user_parent_id::text AS id, end_user_parent_name AS name "
        "FROM data_arr WHERE end_user_parent_name IS NOT NULL AND end_user_parent_id IS NOT NULL"
    )
    _parents = [{"id": r["id"], "name": str(r["name"])} for r in rows]
    ok("Parent index loaded", f"{len(_parents)} parents from data_arr (end_user_parent_id, end_user_parent_name)")
    return _parents


def parent_ids_of(af) -> list[str]:
    """Parent-company ids of a resolved company filter (parent-level matches are their own parent)."""
    ids = af.account_ids if af.multiple else ([af.account_id] if af.account_id else [])
    levels = (af.account_levels if af.multiple else [af.level]) or ["end_user"] * len(ids)
    by_id = {e["id"]: e for e in bootstrap_known_names()}
    out: list[str] = []
    for i, level in zip(ids, levels):
        if level == "parent":
            out.append(i)
        else:
            pid = (af.parent_id if not af.multiple and af.parent_id else (by_id.get(i) or {}).get("parent_id"))
            if pid:
                out.append(pid)
    return list(dict.fromkeys(out))


def all_company_names() -> list[str]:
    """Every searchable name (end users first, then parents) — feeds the NER's open-set matching."""
    names = [e["name"] for e in bootstrap_known_names()] + [p["name"] for p in bootstrap_parent_names()]
    return list(dict.fromkeys(names))


_LEGAL_SUFFIXES = {
    "plc", "llc", "inc", "ltd", "limited", "gmbh", "ag", "sa", "corp", "corporation", "co", "company",
    "the", "of", "and", "group", "holdings", "lp", "bv", "nv", "sas", "srl", "spa", "ab", "as", "oy",
    "kg", "se", "pty", "pte", "llp",
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _coverage(query_tokens: list[str], name_tokens: list[str]) -> float:
    """Share of the query's distinctive words (legal suffixes ignored) that appear in the name."""
    distinctive = [t for t in query_tokens if t not in _LEGAL_SUFFIXES and len(t) >= 2]
    if not distinctive or not name_tokens:
        return 1.0
    hit = sum(1 for t in distinctive if max(_rfuzz.ratio(t, nt) for nt in name_tokens) >= 85)
    return hit / len(distinctive)


def _best_word_ratio(cand: str, name: str) -> float:
    c = cand.lower().strip()
    n = name.lower()
    full = _rfuzz.ratio(c, n) / 100.0
    if " " in c:
        # a multi-word query must find (almost) all of its distinctive words in the name
        cover = _coverage(_tokens(c), _tokens(n))
        return cover * max(full, _rfuzz.token_set_ratio(c, n) / 100.0)
    words = [w for w in n.split() if len(w) >= 4]
    return max(max((_rfuzz.ratio(c, w) / 100.0 for w in words), default=0.0), full)


def _rank(entries: list[dict], raw: str, level: str) -> list[CompanyMatch]:
    raw_lower = raw.lower().strip()
    matches: list[CompanyMatch] = []
    for e in entries:
        name = e["name"]
        score = 1.0 if raw_lower == name.lower() else _best_word_ratio(raw, name)
        if score < _COMPANY_SCORE_FLOOR:
            continue
        matches.append(CompanyMatch(
            account_id=e["id"],
            account_name=name,
            level=level,
            parent_id=e.get("parent_id") if level == "end_user" else e["id"],
            parent_name=e.get("parent_name") if level == "end_user" else name,
            score=round(score, 3),
            matched_raw=raw,
        ))
    # ties: exact full-name match first, then the shortest (most generic) name
    matches.sort(key=lambda x: (-x.score, x.account_name.lower() != raw_lower, len(x.account_name)))
    return matches[:8]


def _is_vendor(raw: str) -> bool:
    """Zscaler itself (with or without a legal suffix) means the whole dataset, never a company filter."""
    t = raw.lower().replace("’s", "").replace("'s", "")
    core = [w for w in re.findall(r"[a-z0-9]+", t) if w not in _LEGAL_SUFFIXES]
    return bool(core) and all(w in {"zscaler", "zs"} for w in core)


def _search(raw: str) -> list[CompanyMatch]:
    if _is_vendor(raw):
        return []
    matches = _rank(bootstrap_known_names(), raw, "end_user")
    if matches:
        return matches
    return _rank(bootstrap_parent_names(), raw, "parent")


async def _resolve_one_account(raw: str) -> list[CompanyMatch]:
    matches = await asyncio.to_thread(_search, raw)
    return [m for m in matches if m.score >= _COMPANY_SCORE_FLOOR]


async def resolve_account(
    raw: Optional[str],
    all_raws: Optional[list[str]] = None,
) -> tuple[list[CompanyMatch], bool]:
    """Returns (matches, is_ambiguous)."""
    names = all_raws if all_raws else ([raw] if raw else [])
    if not names:
        return [], False

    ai = get_ai()
    threshold = ai.pipeline.company_score_threshold

    if len(names) == 1:
        matches = await _resolve_one_account(names[0])
        if not matches:
            return [], False
        # One candidate per entity id
        matches = list({m.account_id: m for m in reversed(matches)}.values())[::-1]
        top = matches[0].score
        exact = [m for m in matches if m.account_name.lower() == names[0].lower().strip()]
        if len({m.account_id for m in exact}) == 1:
            return exact[:1], False
        # A near-exact match with every other candidate clearly weaker is pinned automatically
        if top >= 0.99 and all(m.score <= top - 0.1 for m in matches[1:]):
            return matches[:1], False
        multi_high = sum(1 for m in matches if m.score >= 0.75)
        ambiguous = top < threshold or multi_high > 1
        return matches, ambiguous

    # Multi-company
    per_name = await asyncio.gather(*[_resolve_one_account(n) for n in names])
    resolved: list[CompanyMatch] = []
    seen_ids: set[str] = set()
    ambiguous = False

    for candidates in per_name:
        if not candidates:
            continue
        best = candidates[0]
        if best.account_id not in seen_ids:
            resolved.append(best)
            seen_ids.add(best.account_id)
        if best.score < threshold:
            ambiguous = True

    return resolved, ambiguous


async def resolve_accounts(
    raw: Optional[str],
    all_raws: list[str],
) -> tuple[AccountFilter, list[CompanyMatch], bool]:
    matches, ambiguous = await resolve_account(raw, all_raws if len(all_raws) > 1 else None)
    filter_obj = AccountFilter(account_raw=raw)

    if matches and not ambiguous:
        m0 = matches[0]
        filter_obj = AccountFilter(
            account_raw=raw,
            account_id=m0.account_id,
            account_name=m0.account_name,
            level=m0.level,
            parent_id=m0.parent_id,
            parent_name=m0.parent_name,
        )
        if len(matches) > 1:
            filter_obj.multiple = [m.account_name for m in matches]
            filter_obj.account_ids = [m.account_id for m in matches]
            filter_obj.account_levels = [m.level for m in matches]

    return filter_obj, matches, ambiguous
