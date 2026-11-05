"""SQL Validator — 8-point validation for generated SQL.

No LLM. Pure static analysis using sqlglot AST.
"""
from __future__ import annotations

import re
import sqlglot
import sqlglot.errors
from pipeline.models import SQLContext

_DEAD_TABLES = {"dim_product_hierarchy", "t6_arr_contract", "t6_acv_contract", "dim_account_new"}
_VALID_TABLES = {
    "data_arr", "data_acv", "data_inc_arr", "data_nacv_target",
    "data_quantity", "dim_account", "data_renewal_risk", "data_churn_reason",
    "data_pippeline_curr", "t3_arr_detail",
}
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|COPY)\b",
    re.IGNORECASE,
)


def qualify_join_columns(sql: str, ctx: SQLContext) -> str:
    """When a JOIN is present, qualify metric columns with primary table name."""
    if not ctx.join_clause:
        return sql
    metric_col = ctx.metric.lower()
    primary = ctx.primary_table.lower()
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
        for col in tree.find_all(sqlglot.exp.Column):
            if col.name.lower() == metric_col and not col.table:
                col.set("table", sqlglot.exp.Identifier(this=primary))
        return tree.sql(dialect="postgres")
    except Exception:
        return sql


def pin_group_by_aliases(sql: str) -> str:
    """Rewrite GROUP BY <alias> to select position when alias names a computed expression."""
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.ParseError:
        return sql
    group = tree.args.get("group") if isinstance(tree, sqlglot.exp.Select) else None
    if not group:
        return sql
    computed = {
        e.alias.lower(): i
        for i, e in enumerate(tree.expressions, 1)
        if isinstance(e, sqlglot.exp.Alias) and not isinstance(e.this, sqlglot.exp.Column)
    }
    changed = False
    for i, g in enumerate(group.expressions):
        if isinstance(g, sqlglot.exp.Column) and not g.table and g.name.lower() in computed:
            group.expressions[i] = sqlglot.exp.Literal.number(computed[g.name.lower()])
            changed = True
    return tree.sql(dialect="postgres") if changed else sql


def validate(sql: str, ctx: SQLContext) -> list[str]:
    """Returns list of validation errors (empty list = PASS)."""
    errors: list[str] = []

    # V1: sqlglot parse
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.ParseError as e:
        errors.append(f"V1 Syntax error: {str(e)[:200]}")
        return errors

    sql_up = sql.upper()

    # V2 + V3: table checks
    try:
        ctes = {c.alias.lower() for c in parsed.find_all(sqlglot.exp.CTE)}
        for t in parsed.find_all(sqlglot.exp.Table):
            name = t.name.lower()
            if name in ctes:
                continue
            if name in _DEAD_TABLES:
                errors.append(f"V3 Retired table '{name}' — use primary table '{ctx.primary_table}'")
            elif name not in _VALID_TABLES:
                errors.append(f"V2 Unknown table '{name}' — must be one of: {sorted(_VALID_TABLES)}")
    except Exception:
        pass

    # V4: table-specific column guards (keyed on the PRIMARY table — a data_arr sub-select inside a
    # data_quantity query is legitimate and must not trigger data_arr's column rules)
    primary = (ctx.primary_table or "").upper() if not ctx.extra_where else ""
    if primary == "DATA_ARR":
        if "DATA_ACV" not in sql_up:
            aliases = {a.alias.lower() for a in parsed.find_all(sqlglot.exp.Alias)}
            if "account_name" not in aliases and any(
                c.name.lower() == "account_name" for c in parsed.find_all(sqlglot.exp.Column)
            ):
                errors.append("V4 data_arr has no 'account_name' column — use 'end_user_name' (alias it AS account_name if needed)")
        if re.search(r"\b(IS_LATEST|LEVEL)\b", sql_up):
            errors.append("V4 data_arr has no 'is_latest' or 'level' column — do NOT filter by them")
        if "MRR_ORDER_TYPE" in sql_up and not any(k.startswith("mrr_order_type") for k in ctx.where_values):
            errors.append("V4 Do not filter mrr_order_type — the question names no deal type; exit ARR / ARR = SUM(arr) over the snapshot")
        if re.search(r"\bFROM DATA_ARR\b.*?\bWHERE.*?\bGEO\s*=", sql_up, re.DOTALL):
            errors.append("V4 data_arr uses cfy_geo not geo — use cfy_geo/cfy_area/cfy_region")

    if primary == "DATA_ACV":
        if re.search(r"\bCFY_GEO\b|\bCFY_AREA\b|\bCFY_REGION\b", sql_up):
            errors.append("V4 data_acv uses plain `geo` column, not cfy_geo/cfy_area/cfy_region")
        if re.search(r"\bIS_LATEST\b", sql_up):
            errors.append("V4 data_acv has no 'is_latest' column — do NOT filter by it")

    if primary == "DATA_INC_ARR":
        if re.search(r"\bACCOUNT_ID\s*=", sql_up):
            errors.append("V4 data_inc_arr is keyed on end_user_parent_id, not account_id")
        if "AGGREGATION_LEVEL" not in sql_up:
            errors.append("V4 data_inc_arr requires aggregation_level = 'Level L3' in WHERE")

    if primary == "DATA_QUANTITY":
        if "FISCAL_MONTH" not in sql_up:
            errors.append("V4 data_quantity is a monthly stock: filter one fiscal_month (e.g. fiscal_month = '2026-10-01') or GROUP BY fiscal_month")

    # V5: fiscal format guard
    if re.search(r"=\s*'FY\d{2}'", sql, re.IGNORECASE):
        errors.append("V5 Wrong fiscal_year format — use 'FY 2026' not 'FY26'")
    if re.search(r"=\s*'Q[1-4]FY\d{2}'", sql, re.IGNORECASE):
        errors.append("V5 Wrong fiscal_quarter format — use 'FY 2026 Q1' not 'Q1FY26'")
    if re.search(r"fiscal_quarter\s*=\s*'Q[1-4]'", sql, re.IGNORECASE):
        errors.append("V5 Wrong fiscal_quarter format — use 'FY 2026 Q1' not bare 'Q1'")

    # V6: mutation guard
    if _FORBIDDEN.search(sql):
        errors.append("V6 Mutation statement detected — only SELECT queries are allowed")

    # V7: LIMIT guard
    if "LIMIT" not in sql_up:
        errors.append("V7 Missing LIMIT clause")

    # V8: metric invariants from metrics.yaml (definitions that must never be improvised)
    from core.mdl_registry import get_registry
    metric = get_registry().get(ctx.metric_name)
    if metric:
        for pattern, message in metric.checks:
            if not re.search(pattern, sql, re.IGNORECASE):
                errors.append(f"V8 {message}")

    return errors

