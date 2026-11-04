"""Geo Tool — validates and resolves geography references.

Two levels:
  1. Broad geo (end_user_parent_geo): Americas | APJ | EMEA
  2. Detailed CFY hierarchy (cfy_geo / cfy_area / cfy_region)
"""
from __future__ import annotations

from typing import Any, Optional
from core.settings import get_schema
from pipeline.models import GeoFilter


def get_geo_nodes() -> list[dict[str, str]]:
    """Flatten cfy_hierarchy into a list of {col, value} nodes."""
    schema = get_schema()
    hierarchy = schema.get("cfy_hierarchy", {})
    nodes = []
    for col in ("cfy_geo", "cfy_area", "cfy_region"):
        for val in hierarchy.get(col, []):
            nodes.append({"col": col, "value": val})
    return nodes


def search_geo(phrase: str) -> Optional[dict[str, str]]:
    """Match phrase against cfy_hierarchy nodes."""
    p_lower = phrase.lower().strip()
    nodes = get_geo_nodes()
    # Exact match first
    for n in nodes:
        if n["value"].lower() == p_lower:
            return n
    # Substring match
    for n in nodes:
        if p_lower in n["value"].lower():
            return n
    return None


async def resolve_geo(geo_raw: list[str] | str | None) -> tuple[list[str], list[str]]:
    """Maps raw geo strings to canonical column values (e.g. 'Americas' -> ['AMS ECE', 'AMS MPH'])."""
    if not geo_raw:
        return [], []
    raw_list = [geo_raw] if isinstance(geo_raw, str) else geo_raw

    schema = get_schema()
    aliases = schema.get("geo_aliases", {})
    expand = schema.get("geo_expand", {})

    resolved: list[str] = []
    invalid: list[str] = []

    def _add_expanded(canon: str) -> None:
        for v in expand.get(canon, [canon]):
            if v not in resolved:
                resolved.append(v)

    for raw in raw_list:
        if not raw:
            continue
        key = raw.upper().strip()
        canon = aliases.get(key)
        if canon:
            _add_expanded(canon)
            continue

        partials = [v for k, v in aliases.items() if key in k or k in key]
        if partials:
            for p in partials:
                _add_expanded(p)
        else:
            invalid.append(raw)

    return resolved, invalid


async def resolve_geo_detail(geo_detail_raw: list[str] | str | None) -> list[GeoFilter]:
    """Resolves detailed CFY territory phrases to GeoFilter objects."""
    if not geo_detail_raw:
        return []
    raw_list = [geo_detail_raw] if isinstance(geo_detail_raw, str) else geo_detail_raw

    resolved: list[GeoFilter] = []
    seen = set()

    for phrase in raw_list:
        if not phrase:
            continue
        node = search_geo(phrase)
        if node and node["value"] not in seen:
            seen.add(node["value"])
            resolved.append(GeoFilter(col=node["col"], value=node["value"]))

    return resolved

