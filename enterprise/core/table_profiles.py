"""Table profiles — where each dimension lives in each fact table, and how to filter it.

The same business word is a different column (or no column at all) depending on the table:
  geo     data_arr/data_inc_arr: cfy_geo|cfy_area|cfy_region   data_acv: geo only   pipeline/t3: geo|area|region
  product data_arr/acv/inc_arr/quantity: product_l1..l5   targets: fy27_product_l1..l3
          pipeline: its own sales taxonomy   t3: level + product   renewal risk: product_rl1
  company data_arr: end_user_id / end_user_parent_id   data_inc_arr: parent only   data_acv/pipeline/risk/quantity: account_id (the one key shared by every table;
          end_user_id is attributed differently per table)
When a table lacks a geo/segment column but has account_id, the dimension is applied through the data_arr account
(as of the period's snapshot); when nothing can express the cut, the request is blocked with an explanation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sql.builder import _sql_literal, _where_parts


@dataclass(frozen=True)
class Profile:
    table: str
    period_col: str
    geo: dict[str, str]                      # level ('geo'|'area'|'region') -> column
    segment: Optional[str]
    product: str                             # hier | pipeline | t3 | rl1
    company: str                             # columns | parent | account | none
    has_account_id: bool
    product_prefix: str = ""
    product_levels: int = 5
    fixed: dict[str, Any] = field(default_factory=dict)


_CFY = {"geo": "cfy_geo", "area": "cfy_area", "region": "cfy_region"}
_PLAIN = {"geo": "geo", "area": "area", "region": "region"}

PROFILES: dict[str, Profile] = {p.table: p for p in [
    Profile("data_arr", "fiscal_quarter", _CFY, "market_segment", "hier", "columns", True),
    Profile("data_acv", "fiscal_quarter", {"geo": "geo"}, None, "hier", "account", True),   # end_user_id is attributed differently than in data_arr
    Profile("data_inc_arr", "fiscal_quarter", _CFY, "market_segment", "hier", "parent", False,
            product_levels=3, fixed={"aggregation_level": "Level L3"}),
    Profile("data_nacv_target", "fiscal_quarter", {}, None, "hier", "none", False,
            product_prefix="fy27_", product_levels=3),
    Profile("data_pippeline_curr", "opp_close_qtr", _PLAIN, "market_segment", "pipeline", "account", True),
    Profile("data_renewal_risk", "renewal_qtr", {}, None, "rl1", "account", True,
            fixed={"max_fiscal_month_flag": 1}),
    Profile("t3_arr_detail", "fiscal_quarter", _PLAIN, "market_segment", "t3", "none", False),
    Profile("data_quantity", "fiscal_quarter", {}, None, "hier", "account", True),
    Profile("data_churn_reason", "fiscal_quarter", _PLAIN, None, "hier", "account", True, product_levels=3),
]}

# hierarchy L1 -> the pipeline's own L1 naming
PIPELINE_L1 = {
    "ZIA": "Internet Access and Platform",
    "ZPA": "Private Access",
    "Security for AI": "AI Security",
    "Agentic SecOps": "SecOps",
    "ZS-FLEX": "ZS FLEX",
}

_ARR_DIM_COL = {"geo": "cfy_geo", "area": "cfy_area", "region": "cfy_region", "segment": "market_segment"}


def _in_or_eq(col: str, vals: list[str]) -> dict[str, Any]:
    vals = list(dict.fromkeys(v for v in vals if v))
    return {col: vals[0]} if len(vals) == 1 else {f"{col}__in": vals}


def _product_filters(p: Profile, resolved) -> tuple[dict[str, Any], list[str]]:
    from agents.base_agent import MetricAgent                 # shared level-aware product WHERE
    notes: list[str] = []
    filters = resolved.product_filters or ([resolved.product_filter] if resolved.product_filter else [])
    if not filters:
        return {}, notes
    paths = list(dict.fromkeys(tuple(f.path) for f in filters if f.path))

    if p.product == "hier":
        return MetricAgent._product_where(resolved, p.product_prefix, p.product_levels), notes

    if p.product == "pipeline":
        clauses = []
        for path in paths:
            parts = []
            if path[0] in PIPELINE_L1:
                parts.append(f"product_l1 = {_sql_literal(PIPELINE_L1[path[0]])}")
            elif len(path) == 1:
                parts.append(f"product_l1 = {_sql_literal(path[0])}")
            if len(path) > 1:
                n = _sql_literal(path[-1])
                parts.append(f"(product_l2 = {n} OR product_l3 = {n})")
            clauses.append("(" + " AND ".join(parts) + ")")
        notes.append("pipeline uses its own product naming (e.g. ZIA = 'Internet Access and Platform')")
        return {"__raw_product__": "(" + " OR ".join(clauses) + ")"}, notes

    if p.product == "t3":
        clauses = []
        for path in paths:
            k = min(len(path), 3)
            clauses.append(f"(level = 'L{k}' AND product = {_sql_literal(path[k - 1])})")
        return {"__raw_product__": "(" + " OR ".join(clauses) + ")"}, notes

    if p.product == "rl1":
        clauses = []
        for path in paths:
            conds = " AND ".join(f"product_l{i} = {_sql_literal(v)}" for i, v in enumerate(path[:3], 1))
            clauses.append(f"product_rl1 IN (SELECT DISTINCT product_rl1 FROM data_quantity WHERE {conds} AND product_rl1 IS NOT NULL)")
        notes.append("renewal risk uses reporting products (product_rl1); the product filter is mapped through data_quantity")
        return {"__raw_product__": "(" + " OR ".join(clauses) + ")"}, notes

    return {}, notes


def _company_filters(p: Profile, af) -> tuple[dict[str, Any], list[str], str]:
    from agents.base_agent import MetricAgent
    if not af or not (af.account_id or af.account_name):
        return {}, [], ""
    if p.company == "none":
        return {}, [], "this metric only exists per product — there is no account/parent/company cut"
    if p.company == "columns":
        return MetricAgent._company_where(af), [], ""
    if p.company == "account":
        return MetricAgent._company_account_filter(af), [], ""
    # parent-only tables
    from extraction.tools.company_tool import parent_ids_of
    pids = parent_ids_of(af)
    if not pids:
        return {}, [], "could not determine the parent company for this account"
    return _in_or_eq("end_user_parent_id", pids), ["tracked at parent-company level (no account-level data)"], ""


def table_filters(p: Profile, resolved, arr_quarters: list[str]) -> tuple[dict[str, Any], list[str], str]:
    """Where-values for one table. Returns (where, notes, blocked_reason). The period is added by the caller."""
    where: dict[str, Any] = dict(p.fixed)
    notes: list[str] = []
    via_arr: dict[str, list[str]] = {}

    wanted: list[tuple[str, list[str]]] = []
    if resolved.geo_filter:
        wanted.append(("geo", resolved.geo_filter.values or [resolved.geo_filter.value]))
    if resolved.geo_detail_filter:
        wanted.append((resolved.geo_detail_filter.level, [resolved.geo_detail_filter.value]))
    if resolved.segment_filter:
        wanted.append(("segment", [str(resolved.segment_filter)]))

    for level, vals in wanted:
        col = p.segment if level == "segment" else p.geo.get(level)
        if col:
            if level == "geo" and p.table == "data_acv" and {"AMS ECE", "AMS MPH"} <= set(vals):
                vals = list(vals) + ["Americas"]
            where.update(_in_or_eq(col, vals))
        elif p.has_account_id:
            via_arr.setdefault(_ARR_DIM_COL[level], []).extend(vals)
            notes.append(f"{p.table} has no {level} column — applied through the account's {level} in data_arr")
        else:
            return {}, notes, f"{p.table} has no {level} dimension, so it cannot be cut by {level}"

    if via_arr:
        inner: dict[str, Any] = {"fiscal_quarter__in" if len(arr_quarters) > 1 else "fiscal_quarter":
                                 arr_quarters if len(arr_quarters) > 1 else arr_quarters[0]}
        for c, vals in via_arr.items():
            inner.update(_in_or_eq(c, vals))
        where["__raw_via_arr__"] = "account_id IN (SELECT DISTINCT account_id FROM data_arr WHERE " + " AND ".join(_where_parts(inner)) + ")"

    pw, pnotes = _product_filters(p, resolved)
    where.update(pw)
    notes += pnotes

    cw, cnotes, blocked = _company_filters(p, resolved.account_filter)
    if blocked:
        return {}, notes, blocked
    where.update(cw)
    notes += cnotes
    return where, notes, ""
