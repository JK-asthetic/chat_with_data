"""Customer-company lookup against t6_arr_contract (the ARR snapshot table).

Searches t6_arr_contract.account_name so fuzzy matching only finds companies
that Zscaler actually transacts with, not the full 188k-row account master.
"""
from __future__ import annotations

import psycopg2
from rapidfuzz import fuzz as _rfuzz

from core.db import query_all


def existing(candidates: list[str], exact: bool = False) -> set[str]:
    """Lower-cased subset of `candidates` that exists as an account_name in t6_arr_contract.

    Without `exact`, a prefix match is also accepted ('Oracle' for 'Oracle Corporation').
    A lone common word is only trustworthy with exact=True.
    """
    if not candidates:
        return set()
    prefix = "" if exact else "OR lower(account_name) LIKE c || ' %%'"
    try:
        rows = query_all(
            f"""
            SELECT c FROM unnest(%(c)s::text[]) AS c
            WHERE EXISTS (
                SELECT 1 FROM t6_arr_contract
                WHERE is_latest = true AND (lower(account_name) = c {prefix})
                LIMIT 1
            )
            """,
            {"c": sorted({c.lower() for c in candidates})},
        )
    except psycopg2.Error as e:
        print(f"    ↳ company lookup unavailable ({e.__class__.__name__})")
        return set()
    return {r["c"] for r in rows}


_GENERIC_WORDS = frozenset({
    "bank", "corp", "corporation", "inc", "ltd", "llc", "co", "company",
    "group", "holding", "holdings", "international", "global", "services",
    "solutions", "technologies", "technology", "systems", "consulting",
    "management", "partners", "enterprises", "association", "foundation",
    "limited", "plc", "ag", "gmbh", "sa", "bv", "nv",
})


def _best_word_ratio(cand: str, account_name: str) -> float:
    """Score cand against the account name.

    Strategy: score the FULL account name via WRatio (catches multi-word matches
    like 'Arthur J' → 'Arthur J. Gallagher'), then take the max of that vs
    per-meaningful-word matching (for typos like 'seimnes' → 'Siemens').
    Generic words (bank, corp, inc…) are excluded from per-word scoring so that
    'HDFC Bank' does not score 0.90 against 'Bank OZK' via the word 'bank'.
    """
    c_low = cand.lower()
    name_low = account_name.lower()

    # Full-name ratio (best for multi-word candidate like "Arthur J")
    full_score = _rfuzz.WRatio(c_low, name_low) / 100.0

    # Per-meaningful-word ratio (best for single-word typos like "seimnes")
    meaningful = [w for w in name_low.split() if w and w not in _GENERIC_WORDS and len(w) > 2]
    word_score = max((_rfuzz.WRatio(c_low, w) / 100.0 for w in meaningful), default=0.0) if meaningful else 0.0

    return max(full_score, word_score)


def _transposition_variants(c: str) -> list[str]:
    """Generate single-adjacent-swap variants of c ('orcale' → 'oracle','ocrale',...).

    pg_trgm similarity collapses on transpositions, so widening the shortlist
    with these variants recovers common typos ('orcale'→'oracle', 'seimnes'→'siemens').
    """
    out = [c]
    for i in range(len(c) - 1):
        if c[i] != c[i + 1]:
            out.append(c[:i] + c[i + 1] + c[i] + c[i + 2:])
    return out


def fuzzy_existing(candidates: list[str], threshold: float = 0.70) -> dict[str, str]:
    """Fuzzy-match candidates against dim_account.

    Returns {candidate_lower: best_matched_account_name} for candidates whose
    best per-word similarity meets the threshold.

    Strategy:
      1. Build a shortlist via pg_trgm `%` operator + ILIKE on all ordered
         2-char subsequences of the first 4 chars of the candidate.  This
         covers single AND double transpositions: 'seimnes'[:4]='seim' yields
         'si%' which hits 'Siemens'; 'orcale'[:4]='orca' yields 'or%'.
      2. Rescore each candidate against the best-matching single word of each
         account name using difflib (handles the remaining spelling noise).

    Falls back to pure ILIKE prefix + difflib when pg_trgm isn't installed.
    """
    if not candidates:
        return {}
    uniq = sorted({c.lower() for c in candidates if c.strip()})
    result: dict[str, str] = {}

    for c in uniq:
        if len(c) < 3:
            continue
        # All ordered 2-char subsequences from the first 4 chars cover single and
        # double transpositions: 'seimnes'[:4]='seim' → 'si%' hits 'Siemens'.
        c4 = c[:4]
        prefix_variants = list({
            f"{c4[i]}{c4[j]}%"
            for i in range(len(c4))
            for j in range(i + 1, len(c4))
        })
        shortlist: list[str] = []

        try:
            rows = query_all(
                """
                (
                  SELECT DISTINCT account_name FROM t6_arr_contract
                  WHERE is_latest = true AND lower(account_name) %% %(c)s
                  LIMIT 50
                )
                UNION
                (
                  SELECT DISTINCT account_name FROM t6_arr_contract
                  WHERE is_latest = true AND lower(account_name) LIKE ANY(%(prefixes)s::text[])
                  LIMIT 200
                )
                """,
                {"c": c, "prefixes": prefix_variants},
            )
            shortlist = [r["account_name"] for r in rows]
        except psycopg2.Error:
            try:
                rows = query_all(
                    """
                    SELECT DISTINCT account_name FROM t6_arr_contract
                    WHERE is_latest = true AND lower(account_name) LIKE ANY(%(prefixes)s::text[])
                    LIMIT 200
                    """,
                    {"prefixes": prefix_variants},
                )
                shortlist = [r["account_name"] for r in rows]
            except psycopg2.Error:
                break

        if not shortlist:
            continue

        scored = [(name, _best_word_ratio(c, name)) for name in shortlist]
        scored.sort(key=lambda x: x[1], reverse=True)
        best_name, best_score = scored[0]
        if best_score >= threshold:
            result[c] = best_name

    return result
