"""SKU Tool — resolves SKU / item_name codes to canonical values.

SKUs are a fixed vocabulary — no fuzzy matching needed.
In dry_run: loads vocabulary from data_arr.csv or schema list.
"""
from __future__ import annotations

import re
from typing import Optional
from functools import lru_cache

from core.db import query_all

_sku_cache: Optional[frozenset[str]] = None


@lru_cache(maxsize=1)
def get_sku_vocab() -> frozenset[str]:
    """Load canonical SKU vocabulary from DB or data samples."""
    try:
        rows = query_all("SELECT DISTINCT item_name FROM data_arr WHERE item_name IS NOT NULL LIMIT 2000")
        skus = {r["item_name"].strip().upper() for r in rows if r.get("item_name")}
        if skus:
            return frozenset(skus)
    except Exception:
        pass

    # Built-in common Zscaler SKU patterns as fallback
    return frozenset([
        "ZS-PLATFORM", "ZS-USER-BIZ-EDITION", "ZS-USER-TRANS-EDITION",
        "ZIA-PRO-EDITION", "ZPA-ENTERPRISE", "ZDX-ADV", "ZCC-MOBILE",
        "CASB-CORE", "ZT-BRANCH", "ZT-CLOUD-PRO", "ZCON-SUB",
    ])


def find_skus_in(text: str) -> list[tuple[int, int, str]]:
    """Scan text for known SKU patterns."""
    vocab = get_sku_vocab()
    found = []
    # Tokenize candidate SKU words (containing hyphens or digits)
    for m in re.finditer(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)+\b", text, re.IGNORECASE):
        tok = m.group(0).upper()
        if tok in vocab:
            found.append((m.start(), m.end(), tok))
    return found


def canonical(raw: str) -> Optional[str]:
    vocab = get_sku_vocab()
    u = raw.upper().strip()
    return u if u in vocab else None


async def resolve_skus(sku_raw: list[str] | str | None) -> list[str]:
    if not sku_raw:
        return []
    raw_list = [sku_raw] if isinstance(sku_raw, str) else sku_raw
    resolved = []
    for r in raw_list:
        c = canonical(r)
        if c and c not in resolved:
            resolved.append(c)
        elif r and r.strip() not in resolved:
            resolved.append(r.strip())
    return resolved

