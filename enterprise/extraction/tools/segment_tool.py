"""Market Segment Tool — maps raw segment strings to canonical DB values."""
from __future__ import annotations

from core.settings import get_schema


async def resolve_segments(segment_raw: list[str] | str | None) -> tuple[list[str], list[str]]:
    """Returns (resolved_list, invalid_list)."""
    if not segment_raw:
        return [], []
    raw_list = [segment_raw] if isinstance(segment_raw, str) else segment_raw

    aliases = get_schema().get("segment_aliases", {})
    resolved: list[str] = []
    invalid: list[str] = []

    for raw in raw_list:
        if not raw:
            continue
        key = raw.upper().strip()
        canon = aliases.get(key)
        if canon:
            if canon not in resolved:
                resolved.append(canon)
        else:
            invalid.append(raw)

    return resolved, invalid

