"""Company Tool — fuzzy account name matching.

Phases:
  Phase 1 (dry_run=True):  rapidfuzz WRatio against in-memory list from CSV
  Phase 2 (dry_run=False): pg_trgm similarity on dim_account / data_arr
"""
from __future__ import annotations

import asyncio
from typing import Optional
from rapidfuzz import fuzz as _rfuzz

from pipeline.models import AccountFilter, CompanyMatch
from core.settings import get_ai
from core.db import check_pg_trgm, query_all

_COMPANY_SCORE_FLOOR = 0.70
_known_names: list[dict[str, str]] = []  # [{account_id, account_name}]


def bootstrap_known_names() -> list[dict[str, str]]:
    """Loads accounts from CSV or DB once into memory."""
    global _known_names
    if _known_names:
        return _known_names

    try:
        rows = query_all(
            "SELECT DISTINCT account_id::text AS account_id, account_name "
            "FROM dim_account WHERE account_name IS NOT NULL LIMIT 5000"
        )
        _known_names = [{"account_id": str(r.get("account_id", "")), "account_name": str(r.get("account_name", ""))}
                        for r in rows if r.get("account_name")]
    except Exception:
        _known_names = []
    return _known_names


def _best_word_ratio(cand: str, name: str) -> float:
    words = [w for w in name.lower().split() if w]
    if not words:
        return 0.0
    c = cand.lower()
    return max(_rfuzz.WRatio(c, w) / 100.0 for w in words)


def _search_offline(raw: str) -> list[CompanyMatch]:
    names = bootstrap_known_names()
    matches: list[CompanyMatch] = []
    raw_lower = raw.lower().strip()

    for item in names:
        name = item["account_name"]
        score = 1.0 if raw_lower == name.lower() else _best_word_ratio(raw, name)
        if score >= _COMPANY_SCORE_FLOOR:
            matches.append(CompanyMatch(
                account_id=item["account_id"] or name,
                account_name=name,
                score=round(score, 3),
                matched_raw=raw,
            ))

    matches.sort(key=lambda x: x.score, reverse=True)
    return matches[:8]


def _search_trgm(raw: str) -> list[CompanyMatch]:
    rows = query_all(
        """
        SELECT account_id::text AS account_id, account_name,
               similarity(lower(account_name), %(q)s) AS _sim
        FROM dim_account
        WHERE account_name IS NOT NULL AND lower(account_name) %% %(q)s
        ORDER BY _sim DESC
        LIMIT 8
        """,
        {"q": raw.lower()},
    )
    matches: list[CompanyMatch] = []
    for r in rows:
        name = r["account_name"]
        score = 1.0 if raw.lower() == name.lower() else _best_word_ratio(raw, name)
        matches.append(CompanyMatch(
            account_id=str(r["account_id"]),
            account_name=name,
            score=round(score, 3),
            matched_raw=raw,
        ))
    matches.sort(key=lambda x: x.score, reverse=True)
    return matches


async def _resolve_one_account(raw: str) -> list[CompanyMatch]:
    use_trgm = check_pg_trgm()
    search_fn = _search_trgm if use_trgm else _search_offline
    matches = await asyncio.to_thread(search_fn, raw)
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
        top = matches[0].score
        multi_high = sum(1 for m in matches if m.score >= 0.75)
        ambiguous = top < threshold or multi_high > 1
        return matches, ambiguous

    # Multi-account
    tasks = [_resolve_one_account(n) for n in names]
    per_name = await asyncio.gather(*tasks)
    resolved: list[CompanyMatch] = []
    seen_ids: set[str] = set()
    ambiguous = False

    for raw_name, candidates in zip(names, per_name):
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
        if len(matches) > 1:
            filter_obj = AccountFilter(
                account_raw=raw,
                account_id=matches[0].account_id,
                account_name=matches[0].account_name,
                multiple=[m.account_name for m in matches],
                account_ids=[m.account_id for m in matches],
            )
        else:
            filter_obj = AccountFilter(
                account_raw=raw,
                account_id=matches[0].account_id,
                account_name=matches[0].account_name,
            )

    return filter_obj, matches, ambiguous

