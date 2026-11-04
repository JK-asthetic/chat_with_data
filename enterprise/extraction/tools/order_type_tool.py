"""Order Type Tool — resolves deal motion phrases to canonical DB values."""
from __future__ import annotations

from core.settings import get_schema


async def resolve_order_types(raw: list[str] | str | None) -> list[str]:
    """Maps raw order types ('new logo', 'renewal') to canonical strings."""
    if not raw:
        return []
    raw_list = [raw] if isinstance(raw, str) else raw

    aliases = get_schema().get("order_type_aliases", {})
    resolved = []

    for r in raw_list:
        if not r:
            continue
        key = r.upper().strip()
        canon = aliases.get(key, r)
        if canon not in resolved:
            resolved.append(canon)

    return resolved

