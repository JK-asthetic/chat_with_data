"""
Stage 4 — Deterministic JSON Assembler.

Takes all S2 tool outputs (ResolvedEntities) and produces:
  1. EnrichedQuery  — the canonical enriched JSON (for display/audit)
  2. SQLContext     — the structured context passed to ZLLAMA for SQL generation

100% deterministic — no AI involved at this stage.
"""
from __future__ import annotations

from core.config import get_schema, get_settings
from pipeline.models import (
    Aggregation,
    EnrichedQuery,
    ExtractedQuery,
    Intent,
    ProductFilter,
    ResolvedEntities,
    SQLContext,
)

# Safety cap for queries that are not ranked lists; the validator requires every query to have a LIMIT.
_RESULT_LIMIT = 1000


def _row_limit(ext: ExtractedQuery) -> int:
    """An explicit 'top/bottom N' wins; a ranked list defaults to DEFAULT_LIMIT; anything else gets the safety cap."""
    if ext.limit_n:
        return ext.limit_n
    return get_settings().DEFAULT_LIMIT if ext.intent in (Intent.RANK, Intent.RISK) else _RESULT_LIMIT


def _product_columns(level: int) -> list[str]:
    return [f"product_l{i}" for i in range(1, level + 1)]


def _product_where(products: list[ProductFilter]) -> dict:
    """WHERE entries for the resolved product nodes; each node pins product_l1..product_lN."""
    paths = [p.path for p in products if p.path]
    if not paths:
        return {}
    if len(paths) == 1:
        return {f"product_l{i}": v for i, v in enumerate(paths[0], 1)}
    depths = {len(p) for p in paths}
    if len(depths) == 1:
        depth = depths.pop()
        where = {f"product_l{depth}__in": list(dict.fromkeys(p[-1] for p in paths))}
        if depth > 1:
            where["product_l1__in"] = list(dict.fromkeys(p[0] for p in paths))
        return where
    # nodes at different depths: OR of one conjunction per node
    return {"__or__": [{f"product_l{i}": v for i, v in enumerate(p, 1)} for p in paths]}

# ── Schema DDL builder ────────────────────────────────────────────────────────

def _build_ddl(table: str) -> str:
    s = get_schema()["tables"][table]
    cols = list(s["query_columns"])
    col_lines = ",\n    ".join(f"{c} VARCHAR" for c in cols)
    desc = s.get("description", "")
    return f"-- {desc}\nCREATE TABLE {table} (\n    {col_lines}\n);"


# ── Aggregation strategy ──────────────────────────────────────────────────────

def _compute_aggregation(resolved: ResolvedEntities) -> Aggregation:
    """
    Determine GROUP BY strategy from intent + resolved dimensions.
    Pure logic — no AI.
    """
    intent = resolved.extracted.intent
    has_account   = bool(resolved.account_filter.account_id)
    multi_product = len(resolved.product_filter) > 1
    multi_geo     = len(resolved.geo_filter) > 1

    # group_by_product_level: 0 = none, else product_l1..product_lN down to the deepest level
    # the user named (capped at l3; l4/l5 are detail).
    product_level = min(max((p.deepest_level for p in resolved.product_filter), default=0), 3)

    # For TREND: group by time, not account
    group_account = intent not in (Intent.TREND, Intent.AGGREGATE) or has_account

    # COMPARE: always show breakdown
    show_breakdown = intent == Intent.COMPARE or multi_product or multi_geo

    return Aggregation(
        group_by_product_level = product_level,
        group_by_account       = group_account,
        show_breakdown         = show_breakdown,
    )


# ── WHERE values builder ──────────────────────────────────────────────────────

def _build_where(resolved: ResolvedEntities) -> dict:
    where: dict = {}

    # Fiscal (single quarter, single year, or multi-quarter range)
    f = resolved.fiscal
    if f.quarter_labels:
        if len(f.quarter_labels) == 1:
            where["fiscal_quarter"] = f.quarter_labels[0]
        else:
            where["fiscal_quarter__in"] = f.quarter_labels
    elif f.fiscal_quarter_label:
        where["fiscal_quarter"] = f.fiscal_quarter_label
    elif f.fiscal_year_label:
        where["fiscal_year"] = f.fiscal_year_label

    where.update(_product_where(resolved.product_filter))

    # Geo
    if len(resolved.geo_filter) == 1:
        where["end_user_parent_geo"] = resolved.geo_filter[0]
    elif len(resolved.geo_filter) > 1:
        where["end_user_parent_geo__in"] = resolved.geo_filter

    # Segment
    if len(resolved.segment_filter) == 1:
        where["market_segment"] = resolved.segment_filter[0]
    elif len(resolved.segment_filter) > 1:
        where["market_segment__in"] = resolved.segment_filter

    # Order type (Renewal / Upsell / New)
    if len(resolved.order_type_filter) == 1:
        where["mrr_order_type"] = resolved.order_type_filter[0]
    elif len(resolved.order_type_filter) > 1:
        where["mrr_order_type__in"] = resolved.order_type_filter

    # Account
    af = resolved.account_filter
    if af.account_id and af.account_id != "__all__":
        where["account_id"] = af.account_id
    elif af.account_ids:
        where["account_id__in"] = af.account_ids

    return where


# ── GROUP BY builder ──────────────────────────────────────────────────────────

_INTENT_ORDERBY: dict[str, str | None] = {
    Intent.RANK:      "total_arr DESC",
    Intent.LOOKUP:    None,
    Intent.AGGREGATE: "total_arr DESC",
    Intent.TREND:     "fiscal_year ASC, fiscal_quarter ASC",
    Intent.COMPARE:   "total_arr DESC",
    Intent.DELTA:     "total_arr DESC",
    Intent.RISK:      "total_arr ASC",
}


def _build_group_by(resolved: ResolvedEntities, agg: Aggregation) -> list[str]:
    intent  = resolved.extracted.intent
    groups: list[str] = []

    if intent == Intent.RANK:
        groups = ["end_user_name"]

    elif intent == Intent.LOOKUP:
        groups = ["end_user_name", "fiscal_year", "fiscal_quarter"]

    elif intent == Intent.TREND:
        groups = ["fiscal_year", "fiscal_quarter"]
        if len(resolved.geo_filter) > 1:
            groups.insert(0, "end_user_parent_geo")
        cols = _product_columns(agg.group_by_product_level)
        groups = cols + [g for g in groups if g not in cols]

    elif intent in (Intent.AGGREGATE, Intent.COMPARE, Intent.DELTA, Intent.RISK):
        groups.extend(_product_columns(agg.group_by_product_level))
        if len(resolved.geo_filter) > 1:
            groups.append("end_user_parent_geo")
        if resolved.segment_filter:
            groups.append("market_segment")
        if agg.group_by_account:
            groups.append("end_user_name")
        if not groups:
            groups = []  # single total stat card

    return groups


# ── SQL rules injected into ZLLAMA prompt ─────────────────────────────────────

_SQLCODER_RULES = """
STRICT RULES — follow exactly:
1.  Use end_user_name for individual company names — NEVER end_user_parent_name in SELECT/GROUP BY
2.  Geo column in data_arr is end_user_parent_geo — NEVER 'geo', NEVER 'cfy_geo'
3.  Geo values: 'Americas', 'APJ', 'EMEA' — NEVER 'AMER', 'APAC'
4.  fiscal_year format: 'FY 2026' — NEVER 'FY26', NEVER bare '2026'
5.  fiscal_quarter format: 'FY 2026 Q1' — NEVER 'Q1FY26', NEVER 'Q1'
6.  ALWAYS include LIMIT
7.  Use SUM(arr) AS total_arr for the metric
8.  Only JOIN dim_account if join_clause is provided — otherwise query data_arr ONLY
9.  WHERE values are already resolved — use them exactly as given
10. Return ONLY the SQL — no explanation, no markdown fences
11. Product filters use product_l1..product_l5 exactly as given in the WHERE (e.g. product_l1 = 'ZIA' AND product_l2 = 'SWG')
12. ZIA, ZPA, ZDX etc. are Zscaler PRODUCTS — filter them with the product_l* columns, NOT account filters
13. market_segment column holds segment values (Enterprise, Commercial, SMB, etc.)
14. Multiple values use IN (...) syntax, never multiple separate WHERE conditions
15. NEVER add filters from the question text (company name, product name) that are NOT in the pre-resolved WHERE above
16. If account_id is not in WHERE, do NOT filter by any company or end_user_name
17. mrr_order_type holds the order type (Renewal, Upsell, New); filter it only when it is in the pre-resolved WHERE
""".strip()


# ── Public entry point ────────────────────────────────────────────────────────

def build_context(resolved: ResolvedEntities) -> tuple[EnrichedQuery, SQLContext]:
    """
    S4: deterministic assembler.
    Returns (EnrichedQuery, SQLContext).
    """
    ext    = resolved.extracted
    metric = resolved.metric

    # Compute aggregation strategy
    agg = _compute_aggregation(resolved)

    # Build the canonical enriched JSON
    enriched = EnrichedQuery(
        intent         = ext.intent,
        account_filter = resolved.account_filter,
        product_filter = resolved.product_filter,
        geo_filter     = resolved.geo_filter,
        segment_filter = resolved.segment_filter,
        order_type_filter = resolved.order_type_filter,
        metric         = metric,
        aggregation    = agg,
        fiscal         = resolved.fiscal,
        operator       = ext.operator,
        missing_critical = ext.missing_critical,
    )

    # Determine if we need to JOIN dim_account
    af = resolved.account_filter
    need_join = bool(af.account_id and af.account_id != "__all__") or bool(af.account_ids)
    join_clause = (
        "LEFT JOIN dim_account d ON data_arr.account_id = d.account_id"
        if need_join else None
    )

    # Schema DDL
    tables = [metric.table]
    if need_join:
        tables.append("dim_account")
    schema_ddl = "\n\n".join(_build_ddl(t) for t in tables if t in get_schema()["tables"])

    # WHERE / GROUP BY / ORDER BY
    where_values = _build_where(resolved)
    group_by     = _build_group_by(resolved, agg)
    order_by     = _INTENT_ORDERBY.get(ext.intent)

    # Normalised question
    geo_part  = f" in {', '.join(resolved.geo_filter)}" if resolved.geo_filter else ""
    fiscal    = resolved.fiscal
    period    = fiscal.fiscal_quarter_label or fiscal.fiscal_year_label or (
        f"{fiscal.quarter_labels[0]} to {fiscal.quarter_labels[-1]}" if fiscal.quarter_labels else "")
    fq_part   = f" for {period}" if period else ""
    acct_part = f" for {af.account_name}" if af.account_name else ""
    normalized = f"{ext.raw_query.strip()}{geo_part}{fq_part}{acct_part}".strip()

    ctx = SQLContext(
        normalized_question = normalized,
        intent              = ext.intent,
        metric              = metric.col,
        metric_agg          = "SUM",
        primary_table       = metric.table,
        join_clause         = join_clause,
        schema_ddl          = schema_ddl,
        where_values        = where_values,
        group_by            = group_by,
        order_by            = order_by,
        limit               = _row_limit(ext),
        rules               = _SQLCODER_RULES,
    )

    return enriched, ctx
