"""Standard SQL per metric and cut — the reference definitions (executive_briefing_metrics.sql) with the
question's filters injected.

Used two ways: shown to the LLM as the correct shape (so definitions are never improvised) and as the
deterministic fallback when the LLM cannot produce valid SQL. Filters are applied inside a `WITH b AS
(SELECT * FROM <table> WHERE ...)` so predicates never need table aliases.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sql.builder import _where_parts

NU_TYPES = (
    "new_logo", "new_cust", "new_customer", "newlogo", "new_to_product", "ntp",
    "new_l1_product", "new_l2_product", "new_l3_product", "new_l4_product", "new_l5_product",
    "new_to_l1", "new_to_l2", "new_to_l3", "new_to_l4", "new_to_l5", "upsell",
)
NEW_LOGO_TYPES = ("new_logo", "new_cust", "new_customer", "newlogo")
_NORM = "lower(replace(replace(trim(carve_split_type),'-','_'),' ','_'))"


def _in(types: tuple[str, ...]) -> str:
    return f"{_NORM} IN (" + ",".join(f"'{t}'" for t in types) + ")"


NU_FILTER = _in(NU_TYPES)
NEW_LOGO_FILTER = _in(NEW_LOGO_TYPES)
CHURN_COMMENTS = "comment IN ('Customer Churn','ARR Churn')"
CLOSED = "stage NOT IN ('6 - Closed Won','7 - Closed Lost')"
LATEST_ARR_SNAPSHOT = "(SELECT MAX(fiscal_month_end_date) FROM data_arr WHERE fiscal_month_end_date <= CURRENT_DATE)"
PARENT_MAP = (
    "(SELECT DISTINCT ON (account_id) account_id, end_user_parent_id, end_user_parent_name FROM data_arr "
    f"WHERE end_user_parent_id IS NOT NULL AND fiscal_month_end_date = {LATEST_ARR_SNAPSHOT} ORDER BY account_id) m"
)


def W(where: dict[str, Any], *extra: str) -> str:
    return " AND ".join(_where_parts(where) + [e for e in extra if e]) or "TRUE"


@dataclass
class Plan:
    metric: str
    where: dict[str, dict[str, Any]]          # table -> where (period + filters already included)
    cut: str = "product"                      # total | product | account | parent
    by_quarter: bool = False
    limit: int = 10
    level: int = 1                            # product breakdown level
    variant: str = ""                         # nu: new_logos | pipeline: open|stage|lost|open_deals | churn: top
    qty_level: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


def _order_limit(col: str, plan: Plan, grouped: bool) -> str:
    order = f"ORDER BY {'fiscal_quarter ASC, ' if plan.by_quarter else ''}{col} DESC NULLS LAST"
    return f"{order}" + (f" LIMIT {plan.limit if plan.cut in ('account', 'parent') else max(plan.limit, 100)}" if grouped else "")


def _cols(plan: Plan, product_col: str, account=("account_id", "account_name"), parent=("end_user_parent_id", "end_user_parent_name")) -> list[str]:
    cols = {"product": [product_col], "account": list(account), "parent": list(parent), "total": []}[plan.cut]
    return (["fiscal_quarter"] if plan.by_quarter else []) + cols


def _select_group(cols: list[str]) -> tuple[str, str]:
    return (", ".join(cols) + ", " if cols else ""), (f"GROUP BY {', '.join(cols)} " if cols else "")


# ---------------------------------------------------------------- flow metrics on data_acv
def acv(plan: Plan) -> str:
    cols = _cols(plan, f"product_l{plan.level}")
    sel, grp = _select_group(cols)
    return (f"SELECT {sel}ROUND(SUM(adjusted_acv)) AS acv FROM data_acv WHERE {W(plan.where['data_acv'])} {grp}"
            f"{_order_limit('acv', plan, bool(cols))}")


def nu_acv(plan: Plan) -> str:
    flt = NEW_LOGO_FILTER if plan.variant == "new_logos" else NU_FILTER
    cols = _cols(plan, f"product_l{plan.level}")
    sel, grp = _select_group(cols)
    metric = "new_logo_acv" if plan.variant == "new_logos" else "nu_acv"
    having = f"HAVING SUM(adjusted_acv) > 0 " if plan.variant == "new_logos" else ""
    split = ("ROUND(SUM(adjusted_acv) FILTER (WHERE lower(trim(carve_split_type)) <> 'upsell')) AS new_biz, "
             "ROUND(SUM(adjusted_acv) FILTER (WHERE lower(trim(carve_split_type)) = 'upsell')) AS existing_upsell, "
             if plan.cut == "total" and plan.variant != "new_logos" else "")
    return (f"SELECT {sel}ROUND(SUM(adjusted_acv)) AS {metric}, {split}"
            f"COUNT(DISTINCT account_id) FILTER (WHERE adjusted_acv > 0) AS logos "
            f"FROM data_acv WHERE {W(plan.where['data_acv'], flt)} {grp}{having}"
            f"{_order_limit(metric, plan, bool(cols))}")


# ---------------------------------------------------------------- data_inc_arr (parent / product only)
def _inc_cols(plan: Plan) -> list[str]:
    cut = "parent" if plan.cut == "account" else plan.cut
    p = Plan(**{**plan.__dict__, "cut": cut})
    return _cols(p, f"product_l{min(plan.level, 3)}")


def churn_swap(plan: Plan) -> str:
    cols = _inc_cols(plan)
    sel, grp = _select_group(cols)
    extra = "is_merger_demerger IS NULL AND end_user_parent_name IS NOT NULL AND downsell < 0" if plan.variant == "top" else ""
    return (f"SELECT {sel}ROUND(-SUM(downsell) FILTER (WHERE {CHURN_COMMENTS})) AS churn, "
            f"ROUND(SUM(swap_positive + swap_negative)) AS swap FROM data_inc_arr "
            f"WHERE {W(plan.where['data_inc_arr'], extra)} {grp}{_order_limit('churn', plan, bool(cols))}")


def incr_arr(plan: Plan) -> str:
    cols = _inc_cols(plan)
    sel, grp = _select_group(cols)
    return (f"SELECT {sel}ROUND(SUM(arr_change)) AS incr_arr FROM data_inc_arr "
            f"WHERE {W(plan.where['data_inc_arr'])} {grp}{_order_limit('incr_arr', plan, bool(cols))}")


def nnacv(plan: Plan) -> str:
    by_q = ["fiscal_quarter"] if plan.by_quarter else []
    key = {"product": [f"product_l{min(plan.level, 3)}"], "parent": ["end_user_parent_id"],
           "account": ["end_user_parent_id"], "total": []}[plan.cut]
    ks = by_q + key
    sel_nu = ", ".join(f"{k} AS {k}" for k in ks)
    grp = f"GROUP BY {', '.join(ks)}" if ks else ""
    on = " AND ".join(f"nu.{k} = inc.{k}" for k in ks)
    join = f"FULL JOIN inc ON {on}" if ks else ", inc"
    out = ", ".join(f"COALESCE(nu.{k}, inc.{k}) AS {k}" for k in ks)
    return (
        f"WITH nu AS (SELECT {sel_nu + ', ' if ks else ''}SUM(adjusted_acv) AS nu_acv FROM data_acv "
        f"WHERE {W(plan.where['data_acv'], NU_FILTER)} {grp}), "
        f"inc AS (SELECT {sel_nu + ', ' if ks else ''}COALESCE(SUM(downsell) FILTER (WHERE {CHURN_COMMENTS}), 0) AS churn_neg, "
        f"COALESCE(SUM(swap_positive + swap_negative), 0) AS swap FROM data_inc_arr WHERE {W(plan.where['data_inc_arr'])} {grp}) "
        f"SELECT {out + ', ' if ks else ''}ROUND(COALESCE(nu.nu_acv,0)) AS nu_acv, ROUND(COALESCE(inc.churn_neg,0)) AS churn, "
        f"ROUND(COALESCE(inc.swap,0)) AS swap, "
        f"ROUND(COALESCE(nu.nu_acv,0) + COALESCE(inc.churn_neg,0) + COALESCE(inc.swap,0)) AS nnacv "
        f"FROM nu {join} "
        f"ORDER BY {'fiscal_quarter ASC' if plan.by_quarter else 'nnacv DESC NULLS LAST'}"
        + (f" LIMIT {plan.limit if plan.cut in ('account', 'parent') else max(plan.limit, 100)}" if ks else "")
    )


# ---------------------------------------------------------------- plan (data_nacv_target)
def plan_pct(plan: Plan) -> str:
    n = max(1, min(plan.level, 3))
    cols = ", ".join(f"fy27_product_l{i}" for i in range(1, n + 1))
    t = lambda ty: f"COALESCE(SUM(target) FILTER (WHERE target_type='{ty}'), 0)"
    return (
        f"SELECT {cols}, plan, actual, ROUND(100 * actual / NULLIF(plan, 0)) AS plan_pct FROM ("
        f"SELECT {cols}, {t('ACV')} - {t('Churn')} AS plan, "
        f"{t('ACV Actual')} - GREATEST({t('Churn Actual')}, {t('Churn')}) AS actual "
        f"FROM data_nacv_target WHERE {W(plan.where['data_nacv_target'])} GROUP BY {cols}) x "
        f"{'WHERE plan > 0 ' if n > 1 else ''}ORDER BY plan DESC NULLS LAST LIMIT {max(plan.limit, 15)}"
    )


# ---------------------------------------------------------------- pipeline
def pipeline(plan: Plan) -> str:
    variant = plan.variant or "open"
    flt = {"lost": "stage = '7 - Closed Lost'",
           "open_deals": f"{CLOSED} AND pipeline_acv IS NOT NULL",
           }.get(variant, f"pipeline_type_group = 'Open Pipeline' AND {CLOSED}")
    metric = "lost_acv" if variant == "lost" else "open_pipeline_acv"
    base = f"WITH b AS (SELECT * FROM data_pippeline_curr WHERE {W(plan.where['data_pippeline_curr'], flt)}) "
    q = ["opp_close_qtr"] if plan.by_quarter else []
    if variant == "stage":
        return (base + "SELECT CASE WHEN stage ~ '^5[A-D]' THEN '5 - Procurement' ELSE stage END AS stage, "
                "ROUND(SUM(pipeline_acv)) AS pipeline_acv FROM b GROUP BY 1 ORDER BY 1")
    if plan.cut == "total":
        return base + f"SELECT {', '.join(q) + ', ' if q else ''}ROUND(SUM(pipeline_acv)) AS {metric} FROM b {('GROUP BY ' + ', '.join(q)) if q else ''}"
    if plan.cut == "product":
        col = f"product_l{min(plan.level, 3)}"
        cols = q + [col]
        return (base + f"SELECT {', '.join(cols)}, ROUND(SUM(pipeline_acv)) AS {metric} FROM b GROUP BY {', '.join(cols)} "
                f"ORDER BY {metric} DESC NULLS LAST LIMIT {max(plan.limit, 100)}")
    if plan.cut == "account":
        return (base + f"SELECT b.account_id, d.account_name, ROUND(SUM(b.pipeline_acv)) AS {metric} FROM b "
                "LEFT JOIN dim_account d ON d.account_id = b.account_id GROUP BY b.account_id, d.account_name "
                f"ORDER BY {metric} DESC NULLS LAST LIMIT {plan.limit}")
    return (base + f"SELECT COALESCE(m.end_user_parent_id, b.account_id) AS parent_id, "
            f"COALESCE(m.end_user_parent_name, MAX(d.account_name)) AS parent_name, ROUND(SUM(b.pipeline_acv)) AS {metric} FROM b "
            f"LEFT JOIN {PARENT_MAP} ON m.account_id = b.account_id LEFT JOIN dim_account d ON d.account_id = b.account_id "
            f"GROUP BY 1, m.end_user_parent_name ORDER BY {metric} DESC NULLS LAST LIMIT {plan.limit}")


# ---------------------------------------------------------------- renewal risk
def renewal_risk(plan: Plan) -> str:
    base = f"WITH b AS (SELECT * FROM data_renewal_risk WHERE {W(plan.where['data_renewal_risk'])}) "
    m = "ROUND(SUM(b.renewal_arr)) AS renewal_arr_at_risk_window"
    if plan.cut == "total":
        return base + f"SELECT {m} FROM b"
    if plan.cut == "product":
        return base + f"SELECT product_rl1, ROUND(SUM(renewal_arr)) AS renewal_arr_at_risk_window FROM b GROUP BY product_rl1 ORDER BY 2 DESC NULLS LAST LIMIT {max(plan.limit, 100)}"
    if plan.cut == "account":
        return (base + f"SELECT b.account_id, d.account_name, {m} FROM b LEFT JOIN dim_account d ON d.account_id = b.account_id "
                f"GROUP BY b.account_id, d.account_name ORDER BY 3 DESC NULLS LAST LIMIT {plan.limit}")
    return (base + f"SELECT m.end_user_parent_id, m.end_user_parent_name, {m} FROM b LEFT JOIN {PARENT_MAP} ON m.account_id = b.account_id "
            f"GROUP BY m.end_user_parent_id, m.end_user_parent_name ORDER BY 3 DESC NULLS LAST LIMIT {plan.limit}")


# ---------------------------------------------------------------- quantity family
def quantity(plan: Plan) -> str:
    n = plan.qty_level
    col = f"product_l{n}_qty"
    base = f"WITH b AS (SELECT * FROM data_quantity WHERE {W(plan.where['data_quantity'])}) "
    mo = ["fiscal_month"] if plan.by_quarter else []
    if plan.cut == "total":
        return base + f"SELECT {', '.join(mo) + ', ' if mo else ''}SUM({col}) AS quantity FROM b {('GROUP BY ' + ', '.join(mo)) if mo else ''}"
    if plan.cut == "product":
        cols = mo + [f"product_l{n}"]
        return base + f"SELECT {', '.join(cols)}, SUM({col}) AS quantity FROM b GROUP BY {', '.join(cols)} ORDER BY quantity DESC NULLS LAST LIMIT {max(plan.limit, 100)}"
    if plan.cut == "account":
        cols = mo + ["account_id", "account_name"]
        return base + f"SELECT {', '.join(cols)}, SUM({col}) AS quantity FROM b GROUP BY {', '.join(cols)} ORDER BY quantity DESC NULLS LAST LIMIT {plan.limit}"
    return (base + f"SELECT m.end_user_parent_id, m.end_user_parent_name, SUM(b.{col}) AS quantity FROM b "
            f"LEFT JOIN {PARENT_MAP} ON m.account_id = b.account_id GROUP BY m.end_user_parent_id, m.end_user_parent_name "
            f"ORDER BY quantity DESC NULLS LAST LIMIT {plan.limit}")


def arpu(plan: Plan) -> str:
    key = {"product": "product_l1", "account": "account_id", "parent": "account_id", "total": None}[plan.cut]
    wa, wq = W(plan.where["data_arr"]), W(plan.where["data_quantity"])
    if key is None:
        return (f"SELECT ROUND(e.exit_arr) AS exit_arr, qt.qty AS quantity, ROUND(e.exit_arr / NULLIF(qt.qty, 0), 2) AS arpu FROM "
                f"(SELECT SUM(arr) AS exit_arr FROM data_arr WHERE {wa}) e, "
                f"(SELECT SUM(product_l1_qty) AS qty FROM data_quantity WHERE {wq}) qt")
    return (f"WITH e AS (SELECT {key} AS k, SUM(arr) AS exit_arr FROM data_arr WHERE {wa} GROUP BY 1), "
            f"qt AS (SELECT {key} AS k, SUM(product_l1_qty) AS qty FROM data_quantity WHERE {wq} GROUP BY 1) "
            f"SELECT e.k AS {key}, ROUND(e.exit_arr) AS exit_arr, qt.qty AS quantity, ROUND(e.exit_arr / NULLIF(qt.qty, 0), 2) AS arpu "
            f"FROM e JOIN qt ON qt.k = e.k ORDER BY exit_arr DESC NULLS LAST LIMIT {plan.limit if plan.cut != 'product' else max(plan.limit, 100)}")


def attach_rate(plan: Plan) -> str:
    wq, wall = W(plan.where["data_quantity"]), W(plan.where.get("data_quantity_all", plan.where["data_quantity"]))
    denom = f"(SELECT COUNT(DISTINCT account_id) FROM data_quantity WHERE {wall} AND zs_users_qty > 0)"
    return (f"SELECT product_l1, COUNT(DISTINCT account_id) FILTER (WHERE product_l1_qty > 0) AS owners, {denom} AS all_customers, "
            f"ROUND(100.0 * COUNT(DISTINCT account_id) FILTER (WHERE product_l1_qty > 0) / NULLIF({denom}, 0), 1) AS customer_attach_pct "
            f"FROM data_quantity WHERE {wq} GROUP BY product_l1 ORDER BY owners DESC")


def undeployed_arr(plan: Plan) -> str:
    where = dict(plan.where["t3_arr_detail"])
    level = None if "__raw_product__" in where else f"level = 'L{min(plan.level, 3)}'"
    return ("SELECT product, ROUND(SUM(arr)) AS undeployed_arr FROM t3_arr_detail WHERE "
            + W(where, level or "", "configuration_status IS NOT NULL", "deployed_status IS NOT NULL",
                "lower(trim(deployed_status)) IN ('undeployed','not deployed','limited entitled')")
            + " GROUP BY product ORDER BY undeployed_arr DESC NULLS LAST")


def churn_reason(plan: Plan) -> str:
    return (f"SELECT churn_category, churn_reason, COUNT(DISTINCT account_id) AS accounts, ROUND(SUM(account_arr_change)) AS arr_change "
            f"FROM data_churn_reason WHERE {W(plan.where['data_churn_reason'], 'account_arr_change < 0')} "
            f"GROUP BY churn_category, churn_reason ORDER BY arr_change ASC NULLS LAST LIMIT {max(plan.limit, 25)}")


BUILDERS = {
    "ACV": acv, "NU_ACV": nu_acv, "CHURN": churn_swap, "SWAP": churn_swap, "INCR_ARR": incr_arr, "NNACV": nnacv,
    "NACV": plan_pct, "OPEN_PIPELINE": pipeline, "RENEWAL_RISK": renewal_risk, "QTY": quantity, "ARPU": arpu,
    "ATTACH_RATE": attach_rate, "UNDEPLOYED_ARR": undeployed_arr, "CHURN_REASON": churn_reason,
}


def build(plan: Plan) -> Optional[str]:
    fn = BUILDERS.get(plan.metric)
    if not fn:
        return None
    sql = fn(plan)
    return sql if " LIMIT " in sql.upper() else f"{sql} LIMIT {max(plan.limit, 100)}"


def reference(plan: Plan, cuts: list[str]) -> str:
    """The standard query for this question's cut, plus the other cuts the metric supports (as labelled examples)."""
    seen: list[tuple[str, str]] = []
    for cut in dict.fromkeys([plan.cut] + cuts):
        if cut not in cuts and cut != plan.cut:
            continue
        sql = build(Plan(**{**plan.__dict__, "cut": cut}))
        if sql and sql not in [s for _, s in seen]:
            seen.append((cut, sql))
    return "\n\n".join(f"-- cut: {c}\n{s};" for c, s in seen)
