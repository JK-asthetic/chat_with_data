"""Product hierarchy (product_l1..product_l5) discovered from data_arr, loaded once per process.

A node is identified by its full path, e.g. ('ZIA', 'SWG', 'Core SWG'). In the data a product with
no deeper level repeats its own name down the remaining levels (Firewall, Firewall, Firewall...);
those repeats are the same product, so they are not separate nodes.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

import psycopg2

from core.db import query_all

LEVELS = 5
Path = tuple[str, ...]
Index = dict[str, tuple[Path, ...]]

_INDEX: Optional[Index] = None


def build_index(rows: list[dict]) -> Index:
    """lower-cased node name -> every distinct node (path) with that name, shallowest first."""
    nodes: dict[str, dict[tuple[str, ...], Path]] = defaultdict(dict)
    for r in rows:
        vals = [r.get(f"product_l{i}") for i in range(1, LEVELS + 1)]
        for k in range(1, LEVELS + 1):
            name = vals[k - 1]
            if not name:
                break
            if k >= 2 and name == vals[k - 2]:
                continue  # repeat of the parent: same product, no deeper level
            path = tuple(vals[:k])
            nodes[name.lower()].setdefault(tuple(p.lower() for p in path), path)
    return {n: tuple(sorted(p.values(), key=lambda x: (len(x), x))) for n, p in nodes.items()}


def _index() -> Index:
    global _INDEX
    if _INDEX is None:
        try:
            rows = query_all(
                "SELECT DISTINCT product_l1, product_l2, product_l3, product_l4, product_l5 FROM data_arr"
            )
        except psycopg2.Error as e:
            # Not cached, so the next call retries; callers fall back to alias-only product handling.
            print(f"    ↳ product hierarchy unavailable ({e.__class__.__name__}) — using aliases only")
            return {}
        _INDEX = build_index(rows)
    return _INDEX


def warm() -> int:
    """Load the hierarchy now (one ~3 s DISTINCT scan); returns the number of distinct names."""
    return len(_index())


def find(phrase: str) -> tuple[Path, ...]:
    """Every distinct node named `phrase` (case/whitespace-insensitive), shallowest first."""
    return _index().get(" ".join(phrase.lower().split()), ())


# Plain one-word deep products that we've confirmed are real DB values (not just English words that happen to
# share a name). Review before adding — a word in here is treated as a product everywhere it appears, so a sentence
# like 'ARR by bandwidth consumption' now also reads 'Bandwidth' as a product.
_ALLOWED_PLAIN_DEEP = {"Bandwidth", "Breach", "Breakout", "Dedicated", "Extranet", "Promo", "Zenith"}


def _specific(name: str) -> bool:
    """Specific enough to read a product from free text: several words ('Advanced Sandbox'), a hyphen
    ('BCC-ZIA', 'SD-WAN'), an acronym ('AEM', 'ITDR', 'IoT'), or an explicitly allowed plain word."""
    return (" " in name or "-" in name or any(c.isupper() for c in name[1:])
            or name in _ALLOWED_PLAIN_DEEP)


def matchable_names() -> list[str]:
    """Names S1 may spot in free text: every level 1-3 node, plus the level 4-5 nodes that are `_specific`.
    A plain one-word deep name ('Logging', 'Hardware', 'Bandwidth', 'Promo') is too common an English word
    to read a product from. With the deeper names in play the longest match wins, so 'Advanced Sandbox' is
    not reduced to the 'Sandbox' inside it and 'BCC-ZIA' not to 'ZIA'."""
    return [p[-1] for paths in _index().values() for p in paths if len(p) <= 3 or _specific(p[-1])]


def names(max_level: int = LEVELS) -> list[str]:
    """Node names (original casing) at or above `max_level`."""
    return [p[-1] for paths in _index().values() for p in paths if len(p) <= max_level]
