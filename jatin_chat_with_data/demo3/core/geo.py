"""
Geo territory hierarchy — loaded from schema.yaml (no DB call).

3 levels (sub-region intentionally excluded):
  cfy_geo (L1)    e.g. "AMS ECE", "EMEA", "APJ"
  cfy_area (L2)   e.g. "EMEA DACH", "AMS ENT", "India"
  cfy_region (L3) e.g. "Germany ENT", "France", "AMS Central ENT"

Values are the exact DB strings; search is word-bounded + fuzzy for typos.
"""
from __future__ import annotations

import functools
import re

from rapidfuzz import fuzz as _rfuzz, process as _rprocess

from core.config import get_schema

_CFY_LEVELS = ("cfy_geo", "cfy_area", "cfy_region")
_FUZZY_FLOOR = 85


@functools.lru_cache(maxsize=1)
def _load() -> list[dict]:
    """Flatten schema.yaml cfy_hierarchy into [{col, value}] nodes."""
    hier = get_schema().get("cfy_hierarchy", {}) or {}
    nodes: list[dict] = []
    seen: set[str] = set()
    for col in _CFY_LEVELS:
        for val in hier.get(col, []) or []:
            v = str(val).strip()
            if v and v.upper() not in seen:
                seen.add(v.upper())
                nodes.append({"col": col, "value": v})
    return nodes


def get_geo_nodes() -> list[dict]:
    """All cfy nodes — each is {col, value}."""
    return _load()


def get_geo_values() -> list[str]:
    """Flat list of all canonical cfy values across the 3 levels."""
    return [n["value"] for n in _load()]


def search_geo(phrase: str) -> dict | None:
    """
    Fuzzy-match a phrase against all cfy_geo / cfy_area / cfy_region values.
    Returns {col, value} for the best match, or None if below threshold.
    Prefers longest-exact match (more specific level) over fuzzy.
    """
    nodes = _load()
    if not nodes:
        return None

    # Exact word-bounded match — longest value first so specifics beat prefixes
    for n in sorted(nodes, key=lambda x: len(x["value"]), reverse=True):
        if re.search(r"\b" + re.escape(n["value"]) + r"\b", phrase, re.IGNORECASE):
            return n

    # Fuzzy fallback for typos
    candidates = [n["value"] for n in nodes]
    best = _rprocess.extractOne(phrase, candidates, scorer=_rfuzz.WRatio)
    if not best:
        return None
    val, score, idx = best
    if score < _FUZZY_FLOOR:
        return None
    return nodes[idx]
