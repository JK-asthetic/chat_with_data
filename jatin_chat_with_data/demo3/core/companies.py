"""Customer-company lookup against dim_account, the source of truth for account names."""
from __future__ import annotations

import psycopg2

from core.db import query_all


def existing(candidates: list[str], exact: bool = False) -> set[str]:
    """Lower-cased subset of `candidates` that is an account or parent-account name, or (unless `exact`)
    the first words of one ('Oracle' for 'Oracle Corporation'). A lone common word ('Hello', 'Quick') is
    only trustworthy with exact=True."""
    if not candidates:
        return set()
    prefix = "" if exact else "OR lower(account_name) LIKE c || ' %%' OR lower(end_user_parent_name) LIKE c || ' %%'"
    try:
        rows = query_all(
            f"""
            SELECT c FROM unnest(%(c)s::text[]) AS c
            WHERE EXISTS (
                SELECT 1 FROM dim_account
                WHERE lower(account_name) = c OR lower(end_user_parent_name) = c {prefix}
            )
            """,
            {"c": sorted({c.lower() for c in candidates})},
        )
    except psycopg2.Error as e:
        print(f"    ↳ company lookup unavailable ({e.__class__.__name__})")
        return set()
    return {r["c"] for r in rows}
