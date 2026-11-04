"""SKU lookup — 100% exact match against the fixed t6_arr_contract.sku vocabulary.

The sku column has ~1624 distinct fixed values (SKU codes like
'ZDX-ADV-PROBES-GCM-1', 'BDR', 'INT-ZS-DP-GEN-AI-GCM-1000'). We load them
once, cache in-process, and resolve any SKU hit by exact (case-insensitive)
match — no fuzzy/similarity search.
"""
from __future__ import annotations

import functools
import re
from typing import Optional

from core.db import query_all


@functools.lru_cache(maxsize=1)
def _load_skus() -> dict[str, str]:
    """Returns {UPPERCASE_SKU: canonical_db_value} for every distinct sku in t6_arr_contract."""
    try:
        rows = query_all(
            "SELECT DISTINCT sku FROM t6_arr_contract WHERE sku IS NOT NULL AND is_latest = true"
        )
    except Exception as e:
        print(f"    ↳ SKU vocabulary load failed ({e.__class__.__name__}: {e})")
        return {}
    out: dict[str, str] = {}
    for r in rows:
        name = (r.get("sku") or "").strip()
        if name:
            out[name.upper()] = name
    return out


def all_skus() -> dict[str, str]:
    """{UPPERCASE: canonical} map of every known SKU."""
    return _load_skus()


def is_sku(token: str) -> bool:
    """Exact-match check (case-insensitive). No fuzzy."""
    if not token:
        return False
    return token.strip().upper() in _load_skus()


def canonical(token: str) -> Optional[str]:
    """Return canonical DB form of `token` if it is a known SKU, else None."""
    return _load_skus().get(token.strip().upper())


# Token we scan for in free text: alphanumerics plus hyphen, length >= 2.
# Matches both 'BDR' and 'ZDX-ADV-PROBES-GCM-1'.
_SKU_TOKEN_RE = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9\-]{1,}\b")


def find_skus_in(text: str) -> list[tuple[int, int, str]]:
    """Scan free text for any token/phrase that is a 100% match to a known SKU.

    Returns list of (start, end, canonical_sku) spans. Longest-match-wins within
    the same starting position — "ZDX-ADV-PROBES-GCM-1" wins over any shorter
    prefix that also happens to be a known SKU.
    """
    if not text:
        return []
    vocab = _load_skus()
    if not vocab:
        return []

    hits: list[tuple[int, int, str]] = []
    for m in _SKU_TOKEN_RE.finditer(text):
        tok = m.group(0)
        canon = vocab.get(tok.upper())
        if canon:
            hits.append((m.start(), m.end(), canon))

    # Drop any hit whose span is fully contained inside a longer hit
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    kept: list[tuple[int, int, str]] = []
    for s, e, c in hits:
        if any(ks <= s and e <= ke and (ks, ke) != (s, e) for ks, ke, _ in kept):
            continue
        kept.append((s, e, c))
    return kept
