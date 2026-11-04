"""Statistical Sanity Checks — catches 'valid SQL, wrong answer' issues.

No LLM. Pure statistical evaluation on result rows.
"""
from __future__ import annotations

from typing import Any
from pipeline.models import QueryResult, SQLContext, SanityWarning


def sanity_check(result: QueryResult, ctx: SQLContext) -> list[SanityWarning]:
    warnings: list[SanityWarning] = []

    if not result.success or not result.rows:
        if result.success and result.row_count == 0 and ctx.where_values:
            filter_str = ", ".join(f"{k}='{v}'" for k, v in ctx.where_values.items())
            warnings.append(SanityWarning(
                code="S1_ZERO_ROWS",
                message=f"0 rows returned with filters: {filter_str}. Check filter values or try relaxing some.",
            ))
        return warnings

    # Metric outlier detection
    metric_col = next((c for c in result.columns if "arr" in c.lower() or "acv" in c.lower() or "target" in c.lower() or "qty" in c.lower()), None)
    if not metric_col:
        return warnings

    try:
        values = [float(r[metric_col]) for r in result.rows if r.get(metric_col) is not None]
    except (TypeError, ValueError):
        return warnings

    if not values:
        return warnings

    total = sum(values)
    # S2 Outlier: Single row dominates > 50%
    if total > 0 and len(values) > 1:
        dominant = max(values) / total
        if dominant > 0.5:
            top_name = result.rows[values.index(max(values))].get("account_name",
                       result.rows[values.index(max(values))].get("end_user_name", "Top entry"))
            warnings.append(SanityWarning(
                code="S2_OUTLIER",
                message=f"{top_name} represents {dominant:.0%} of the total metric value shown.",
            ))

    # S4 Row count reasonability
    if ctx.limit and result.row_count > ctx.limit:
        warnings.append(SanityWarning(
            code="S4_ROW_COUNT",
            message=f"Result row count ({result.row_count}) exceeded requested limit ({ctx.limit}).",
        ))

    return warnings

