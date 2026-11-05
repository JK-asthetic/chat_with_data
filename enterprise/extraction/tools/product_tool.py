"""Product Tool — classifies raw product phrases against dim_product_hierarchy (L1..L5).

No LLM. Every phrase is matched to hierarchy nodes (name + level + full path):
  * exactly one node  -> resolved ProductFilter at that level
  * several nodes     -> ambiguous; every distinct path is returned as a candidate for the user
    (the same name can live at different levels / branches, e.g. 'Firewall')
Synonyms in schema.yaml (product_aliases) only translate a phrase to a hierarchy name.
"""
from __future__ import annotations

import re
from typing import Optional

from core import hierarchy
from core.settings import get_schema
from pipeline.models import ProductFilter

_LEVEL_RE = re.compile(
    r"\b(?:all|each|every|by|per|across|for)\s+(?:the\s+)?(?:product\s+)?(?:l|level\s*|lvl\s*)([1-5])(?:\s*level)?(?:\s*products?)?\b"
    r"|\bl\s?([1-5])\s*(?:level\s*)?products?\b"
    r"|\bproducts?\s+(?:at\s+)?(?:l|level\s*)\s?([1-5])\b"
    r"|\b(?:level|lvl)\s*([1-5])\s*products?\b",
    re.IGNORECASE,
)


def detect_product_level(text: str) -> Optional[int]:
    """'all L1 level products' / 'by L3 product' -> 1 / 3 (a breakdown level, not a filter)."""
    m = _LEVEL_RE.search(text or "")
    if not m:
        return None
    return int(next(g for g in m.groups() if g))


def _drop_ancestors(filters: list[ProductFilter]) -> list[ProductFilter]:
    """'ZIA SWG ARR' names a product and its own sub-product: the narrower one wins."""
    paths = [f.path for f in filters]
    return [
        f for f, p in zip(filters, paths)
        if not any(len(q) > len(p) and q[:len(p)] == p for q in paths)
    ]


def _collapse_descendants(nodes: list[hierarchy.Node]) -> list[hierarchy.Node]:
    """If a candidate sits inside another candidate's subtree, the broader one already covers it."""
    return [n for n in nodes if not any(o is not n and o.level < n.level and n.path[:o.level] == o.path for o in nodes)]


def _nodes_for(raw: str, aliases: dict[str, str]) -> list[hierarchy.Node]:
    key = raw.strip()
    nodes = hierarchy.find(key)                       # the phrase is itself a hierarchy name
    if not nodes:
        canon = aliases.get(key.upper())              # synonym -> hierarchy name
        if canon:
            nodes = hierarchy.find(canon)
    if not nodes:
        nodes = hierarchy.fuzzy(key)                  # typo tolerance
    if not nodes:
        partial = list(dict.fromkeys(v for a, v in aliases.items() if key.upper() in a or a in key.upper()))
        for canon in partial:
            nodes.extend(hierarchy.find(canon))
    return _collapse_descendants(nodes)


def resolve_products(
    products_raw: list[str],
) -> tuple[list[ProductFilter], bool, dict[str, list[str]], dict[str, list[list[str]]]]:
    """Maps raw product phrases -> ProductFilter objects.

    Returns:
      (resolved, ambiguous, candidates_map (unused, kept for API stability), hierarchy_candidates)
    where hierarchy_candidates maps a raw phrase to its alternative full paths (l1..lk).
    """
    aliases: dict[str, str] = get_schema().get("product_aliases", {})

    resolved: list[ProductFilter] = []
    ambiguous = False
    hierarchy_candidates: dict[str, list[list[str]]] = {}

    for raw in products_raw:
        if not raw:
            continue
        nodes = _nodes_for(raw, aliases)
        if len(nodes) == 1:
            resolved.append(ProductFilter.from_path(nodes[0].path))
        elif len(nodes) > 1:
            hierarchy_candidates[raw] = [list(n.path) for n in nodes]
            ambiguous = True

    return _drop_ancestors(resolved), ambiguous, {}, hierarchy_candidates
