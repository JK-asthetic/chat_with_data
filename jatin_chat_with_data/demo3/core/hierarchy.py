"""Product hierarchy for t6_arr_contract (product + level columns).

t6_arr_contract stores one row per product at a given level (L1-L5).
The hierarchy is loaded from schema.yaml `product_hierarchy` (L1 families with
their L2 sub-products), supplemented by a live DISTINCT query to pick up
any new products added after the last schema update.

A node path looks like ('ZIA',) for L1 or ('ZIA', 'SWG') for L2.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from typing import Optional

import psycopg2

from core.db import query_all

LEVELS = 5
Path   = tuple[str, ...]
Index  = dict[str, tuple[Path, ...]]

_INDEX: Optional[Index] = None


def _load_from_schema() -> list[dict]:
    """Build pseudo-rows from schema.yaml product_hierarchy (offline, fast)."""
    try:
        from core.config import get_schema
        hier = get_schema().get("product_hierarchy", {})
        rows = []
        for l1, meta in hier.items():
            rows.append({"product": l1, "level": "L1", "parent": None})
            for l2 in (meta.get("l2_values") or []):
                rows.append({"product": l2, "level": "L2", "parent": l1})
        return rows
    except Exception:
        return []


def _load_from_db() -> list[dict]:
    """Fallback: discover products from t6_arr_contract DISTINCT scan."""
    try:
        return query_all(
            "SELECT DISTINCT product, level FROM t6_arr_contract "
            "WHERE is_latest = true AND product IS NOT NULL ORDER BY level, product"
        )
    except psycopg2.Error as e:
        print(f"    ↳ product hierarchy unavailable ({e.__class__.__name__}) — using schema only")
        return []


def build_index_from_rows(rows: list[dict]) -> Index:
    """Build the name→paths index from (product, level, parent?) rows."""
    nodes: dict[str, dict[tuple[str, ...], Path]] = defaultdict(dict)

    l1_products: list[str] = []
    l2_map: dict[str, str] = {}  # l2_name -> l1_parent

    for r in rows:
        prod  = (r.get("product") or "").strip()
        level = (r.get("level") or "L1").upper()
        parent = r.get("parent")
        if not prod:
            continue
        if level == "L1":
            l1_products.append(prod)
            path = (prod,)
            nodes[prod.lower()].setdefault(path, path)
        elif level == "L2":
            if parent:
                path = (parent, prod)
            else:
                path = (prod,)
            nodes[prod.lower()].setdefault(path, path)
            if parent:
                l2_map[prod.lower()] = parent
        else:
            path = (prod,)
            nodes[prod.lower()].setdefault(path, path)

    return {n: tuple(sorted(p.values(), key=lambda x: (len(x), x))) for n, p in nodes.items()}


def _index() -> Index:
    global _INDEX
    if _INDEX is None:
        rows = _load_from_schema()
        if not rows:
            rows = _load_from_db()
        _INDEX = build_index_from_rows(rows)
    return _INDEX


def resolve_product(name: str) -> Optional[list[str]]:
    """Return the full path for a product name, e.g. 'SWG' → ['ZIA', 'SWG']."""
    paths = _index().get(name.lower())
    if paths:
        return list(paths[0])  # shallowest path first
    return None


def warm() -> int:
    """Load the hierarchy now; returns number of distinct product names."""
    return len(_index())


def find(phrase: str) -> tuple[Path, ...]:
    """Every distinct node named `phrase` (case/whitespace-insensitive), shallowest first."""
    return _index().get(" ".join(phrase.lower().split()), ())


_ALLOWED_PLAIN_DEEP = {"Bandwidth", "Breach", "Breakout", "Dedicated", "Extranet", "Promo", "Zenith"}


def _specific(name: str) -> bool:
    return (" " in name or "-" in name or any(c.isupper() for c in name[1:])
            or name in _ALLOWED_PLAIN_DEEP)


def matchable_names() -> list[str]:
    """Names S1 may spot in free text: every L1-L2 node, plus deeper nodes that are specific enough."""
    return [p[-1] for paths in _index().values() for p in paths if len(p) <= 3 or _specific(p[-1])]


def names(max_level: int = LEVELS) -> list[str]:
    """Node names (original casing) at or above `max_level`."""
    return [p[-1] for paths in _index().values() for p in paths if len(p) <= max_level]
