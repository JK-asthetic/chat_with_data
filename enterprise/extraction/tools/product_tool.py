"""Product Tool — resolves raw product phrases to ProductFilter objects.

No LLM. Uses product hierarchy loaded from schema.yaml and catalog rules.
"""
from __future__ import annotations

from typing import Any
from core.settings import get_schema
from pipeline.models import ProductFilter


def _drop_ancestors(filters: list[ProductFilter]) -> list[ProductFilter]:
    """'ZIA SWG ARR' names a product and its own sub-product: narrower one wins."""
    paths = [f.path for f in filters]
    return [
        f for f, p in zip(filters, paths)
        if not any(len(q) > len(p) and q[:len(p)] == p for q in paths)
    ]


def resolve_products(
    products_raw: list[str],
) -> tuple[list[ProductFilter], bool, dict[str, list[str]], dict[str, list[list[str]]]]:
    """Maps raw product phrases → ProductFilter objects.

    Returns:
      (resolved, ambiguous, candidates_map, hierarchy_candidates)
    """
    schema = get_schema()
    aliases: dict[str, str] = schema.get("product_aliases", {})
    hierarchy: dict[str, Any] = schema.get("product_hierarchy", {})

    resolved: list[ProductFilter] = []
    ambiguous = False
    candidates: dict[str, list[str]] = {}
    hierarchy_candidates: dict[str, list[list[str]]] = {}

    for raw in products_raw:
        if not raw:
            continue
        key = raw.upper().strip()

        # Check exact alias
        canonical_name = aliases.get(key)
        if canonical_name:
            # Check if canonical name is an L1 family
            if canonical_name in hierarchy:
                resolved.append(ProductFilter(l1=canonical_name, deepest_level=1))
                continue
            # Check if canonical name is an L2 under some family
            found_l2 = False
            for l1_name, l1_info in hierarchy.items():
                l2_values = l1_info.get("l2_values", [])
                if any(canonical_name.lower() == v.lower() for v in l2_values):
                    resolved.append(ProductFilter(l1=l1_name, l2=canonical_name, deepest_level=2))
                    found_l2 = True
                    break
            if found_l2:
                continue
            resolved.append(ProductFilter(l1=canonical_name, deepest_level=1))
            continue

        # Check direct match in L1 hierarchy keys
        matched_l1 = next((k for k in hierarchy if k.upper() == key), None)
        if matched_l1:
            resolved.append(ProductFilter(l1=matched_l1, deepest_level=1))
            continue

        # Check direct match in L2 values across hierarchy
        l2_matches = []
        for l1_name, l1_info in hierarchy.items():
            for v in l1_info.get("l2_values", []):
                if v.upper() == key:
                    l2_matches.append((l1_name, v))

        if len(l2_matches) == 1:
            resolved.append(ProductFilter(l1=l2_matches[0][0], l2=l2_matches[0][1], deepest_level=2))
            continue
        elif len(l2_matches) > 1:
            hierarchy_candidates[raw] = [[m[0], m[1]] for m in l2_matches]
            ambiguous = True
            continue

        # Partial matching across aliases
        partials = list(dict.fromkeys(
            val for alias, val in aliases.items()
            if key in alias or alias in key
        ))
        if len(partials) == 1:
            resolved.append(ProductFilter(l1=partials[0], deepest_level=1))
        elif partials:
            candidates[raw] = partials
            ambiguous = True

    return _drop_ancestors(resolved), ambiguous, candidates, hierarchy_candidates

