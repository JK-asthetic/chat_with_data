"""SQL Prompt Builder — constructs LLM prompts for metric SQL generation.

Metric-specific prompt bodies keep the prompt minimal and tailored, reducing
token cost and maximizing LLM precision.
"""
from __future__ import annotations

from typing import Any, Optional
from pipeline.models import SQLContext
from core.mdl_registry import MetricDefinition

_SHARED_INFRA = """
### Infrastructure Rules (apply to every query)
- ALWAYS include LIMIT
- fiscal_year format: 'FY 2026' — NEVER 'FY26' or bare '2026'
- fiscal_quarter format: 'FY 2026 Q1' — NEVER 'Q1FY26' or bare 'Q1'
- WHERE values are pre-resolved and exhaustive — add NOTHING beyond what is listed.
- COUNT(DISTINCT account_id) for account counts.
- NULLIF every denominator (division-by-zero prevention).
- Return ONLY valid Postgres SQL — no markdown, no comments, no explanation.
- Use IN (...) for multiple values.
""".strip()


def _sql_literal(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _where_parts(where_values: dict[str, Any]) -> list[str]:
    parts = []
    for col, val in where_values.items():
        if col.startswith("_"):
            continue
        if col.endswith("__in"):
            c = col[:-4]
            vals = ", ".join(_sql_literal(x) for x in val)
            parts.append(f"{c} IN ({vals})")
        elif col.endswith("__not_in"):
            c = col[:-8]
            vals = ", ".join(_sql_literal(x) for x in val)
            parts.append(f"{c} NOT IN ({vals})")
        elif col.endswith("__gte"):
            c = col[:-5]
            parts.append(f"{c} >= {_sql_literal(val)}")
        elif col.endswith("__lte"):
            c = col[:-5]
            parts.append(f"{c} <= {_sql_literal(val)}")
        else:
            parts.append(f"{col} = {_sql_literal(val)}")
    return parts


def _format_where(where_values: dict[str, Any]) -> str:
    if not where_values:
        return "  -- no filters (return all rows)"
    return "\n".join(f"  {p}" for p in _where_parts(where_values))


def build_skeleton(ctx: SQLContext) -> str:
    """Deterministic fallback skeleton query."""
    tbl_prefix = f"{ctx.primary_table}." if ctx.join_clause else ""
    metric_col = ctx.metric
    alias_col = f"total_{metric_col}" if not metric_col.startswith("total_") else metric_col
    metric_expr = f"{ctx.metric_agg}({tbl_prefix}{metric_col}) AS {alias_col}"

    group_cols = ctx.group_by or ["account_id"]
    select_cols = list(group_cols) + [metric_expr]

    lines = [f"SELECT {', '.join(select_cols)}"]
    lines.append(f"FROM {ctx.primary_table}")
    if ctx.join_clause:
        lines.append(ctx.join_clause)

    where_items = _where_parts(ctx.where_values)
    if where_items:
        lines.append("WHERE " + "\n  AND ".join(where_items))

    if ctx.group_by:
        lines.append(f"GROUP BY {', '.join(group_cols)}")
    if ctx.order_by:
        lines.append(f"ORDER BY {ctx.order_by}")
    lines.append(f"LIMIT {ctx.limit};")

    return "\n".join(lines)


def build_prompt(
    ctx: SQLContext,
    metric_def: MetricDefinition,
    error_feedback: Optional[str] = None,
    failed_sql: Optional[str] = None,
) -> str:
    where_block = _format_where(ctx.where_values)
    join_block = f"-- JOIN: {ctx.join_clause}" if ctx.join_clause else "-- No JOIN needed"
    group_block = ", ".join(ctx.group_by) if ctx.group_by else "-- no GROUP BY"
    order_block = ctx.order_by or "-- no ORDER BY"

    rules_lines = "\n".join(f"- {r}" for r in metric_def.sql_rules)

    error_block = ""
    if error_feedback:
        prev = f"Your previous SQL:\n{failed_sql}\n\n" if failed_sql else ""
        error_block = f"""
### Previous attempt failed — fix this error:
{prev}Errors:
{error_feedback}
"""

    return f"""### Task
Write Postgres SQL to answer: {ctx.normalized_question}

### Database Schema
{ctx.schema_ddl}

{_SHARED_INFRA}

### Rules for metric: {metric_def.display_name} ({metric_def.table})
{rules_lines}

### WHERE (pre-resolved — use EXACTLY these filters, add NOTHING else)
Table:    {ctx.primary_table}
{join_block}
WHERE:
{where_block}
GROUP BY: {group_block}
ORDER BY: {order_block}
LIMIT:    {ctx.limit}
{error_block}
### SQL
"""

