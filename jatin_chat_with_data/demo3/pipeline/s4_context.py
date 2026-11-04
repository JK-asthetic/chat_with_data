"""
Stage 4 — Deterministic JSON Assembler.

Takes all S2 tool outputs (ResolvedEntities) and produces:
  1. EnrichedQuery  — the canonical enriched JSON (for display/audit)
  2. SQLContext     — the structured context passed to ZLLAMA for SQL generation

Metric-family routing (single source of truth: schema.yaml + MDL):
  ARR family   → data_arr   (snapshot: fiscal_month_end_date = end-of-quarter; trend: multi-quarter)
  ACV family   → data_acv   (adjusted_acv; carve_split_type for NNACV/deal-motion)
  INC/CHURN    → data_inc_arr (aggregation_level = 'Level L3' always; downsell for CHURN)
  NACV target  → data_nacv_target (planning/target table, product-level only)
  QTY          → data_quantity (fiscal_month_m_of_quarter = 'M3' snapshot always)

Each family has its own WHERE builder and SQL rules injected into the LLM prompt.
100% deterministic — no AI involved at this stage.
"""
from __future__ import annotations

from core.config import get_schema, get_settings
from core import mdl as _mdl
from pipeline.models import (
    Aggregation,
    EnrichedQuery,
    ExtractedQuery,
    GeoFilter,
    Intent,
    ProductFilter,
    ResolvedEntities,
    SQLContext,
)

_RESULT_LIMIT = 1000


def _row_limit(ext: ExtractedQuery) -> int:
    if ext.limit_n:
        return ext.limit_n
    return get_settings().DEFAULT_LIMIT if ext.intent in (Intent.RANK, Intent.RISK) else _RESULT_LIMIT


# ── Product WHERE helpers ─────────────────────────────────────────────────────

def _product_where(products: list[ProductFilter]) -> dict:
    """WHERE entries for t6-style tables: `product` + `level` columns."""
    if not products:
        return {"level": "L1"}

    names: list[str] = []
    levels: list[int] = []
    for p in products:
        path = p.path
        if not path:
            continue
        names.append(path[-1])
        levels.append(p.deepest_level if p.deepest_level > 0 else 1)

    if not names:
        return {"level": "L1"}

    level_str = f"L{levels[0]}"

    if len(names) == 1:
        return {"product": names[0], "level": level_str}

    unique_levels = set(f"L{l}" for l in levels)
    if len(unique_levels) == 1:
        return {"product__in": names, "level": level_str}

    return {
        "__or__": [{"product": n, "level": f"L{l}"} for n, l in zip(names, levels)]
    }


def _product_where_flat(products: list[ProductFilter]) -> dict:
    """WHERE entries for flat-column tables (data_arr, data_acv, data_inc_arr, data_quantity).
    Uses product_l1..product_l5 columns."""
    if not products:
        return {}

    names: list[str] = []
    levels: list[int] = []
    for p in products:
        path = p.path
        if not path:
            continue
        names.append(path[-1])
        levels.append(p.deepest_level if p.deepest_level > 0 else 1)

    if not names:
        return {}

    col = f"product_l{levels[0]}"
    if len(names) == 1:
        return {col: names[0]}
    return {f"{col}__in": names}


# ── Table router ─────────────────────────────────────────────────────────────

_ACV_ONLY_ORDER_TYPES = {
    "NEW_CUST", "NEW_L1_PRODUCT", "NEW_L2_PRODUCT", "NEW_L3_PRODUCT",
    "NEW_L4_PRODUCT", "NEW_L5_PRODUCT", "Expansion",
}


_NACV_ACCOUNT_INTENTS = {Intent.RANK, Intent.LOOKUP, Intent.COMPARE, Intent.DELTA}


def _route_table(resolved: ResolvedEntities) -> str:
    """Choose primary table. Metric family always wins."""
    metric_table = resolved.metric.table
    # ACV family (data_acv) — NNACV and ACV both route here
    if metric_table == "data_acv":
        return "data_acv"
    # Incremental ARR and CHURN both route to data_inc_arr
    if metric_table == "data_inc_arr":
        return "data_inc_arr"
    # NACV: data_nacv_target is product-only (no account dimension).
    # When user asks for companies (RANK/LOOKUP/COMPARE) or names a specific account,
    # re-route to data_acv — new ACV bookings by account.
    if metric_table == "data_nacv_target":
        has_account = bool(resolved.account_filter.account_id or resolved.account_filter.multiple)
        if has_account or resolved.extracted.intent in _NACV_ACCOUNT_INTENTS:
            return "data_acv"   # _build_where_data_acv will add NNACV filter via metric.variant
        return "data_nacv_target"
    # License/seat quantity
    if metric_table == "data_quantity":
        return "data_quantity"
    # Safety: if order_type_filter contains ACV-specific deal-motion values
    # (NEW_CUST, Expansion, NEW_L*_PRODUCT) but metric defaulted to ARR,
    # re-route to data_acv — these values don't exist in data_arr.mrr_order_type.
    if any(ot in _ACV_ONLY_ORDER_TYPES for ot in resolved.order_type_filter):
        return "data_acv"
    # All ARR queries → data_arr (snapshot or trend, same table)
    return "data_arr"


# ── Fiscal label → calendar date ──────────────────────────────────────────────

def _fiscal_label_to_date_range(label: str) -> "tuple[str, str] | None":
    """Convert 'FY 2027 Q2' → ('2026-11-01', '2027-01-31'). Returns None if unparseable."""
    import re as _re
    m = _re.match(r"FY\s*(\d{4})\s*Q(\d)", label.strip(), _re.I)
    if not m:
        return None
    fy, q = int(m.group(1)), int(m.group(2))
    # Zscaler FY starts Aug 1. Q1=Aug-Oct, Q2=Nov-Jan, Q3=Feb-Apr, Q4=May-Jul
    starts = {1: (fy - 1, 8, 1),  2: (fy - 1, 11, 1), 3: (fy, 2, 1), 4: (fy, 5, 1)}
    ends   = {1: (fy - 1, 10, 31), 2: (fy, 1, 31),     3: (fy, 4, 30), 4: (fy, 7, 31)}
    sy, sm, sd = starts[q]
    ey, em, ed = ends[q]
    return f"{sy:04d}-{sm:02d}-{sd:02d}", f"{ey:04d}-{em:02d}-{ed:02d}"


def _current_fiscal_quarter() -> str:
    from datetime import date
    d = date.today()
    y, m = d.year, d.month
    if 8 <= m <= 10:
        fy, q = y + 1, 1
    elif m >= 11:
        fy, q = y + 1, 2
    elif m == 1:
        fy, q = y, 2
    elif 2 <= m <= 4:
        fy, q = y, 3
    else:
        fy, q = y, 4
    return f"FY {fy} Q{q}"


# ── Renewal helpers ───────────────────────────────────────────────────────────

_RENEWAL_KW = ("renewal", "renew", "expire", "expir", "contract end")


def _is_renewal_query(raw_query: str) -> bool:
    q = raw_query.lower()
    return any(kw in q for kw in _RENEWAL_KW)


# ── WHERE builder: data_arr ──────────────────────────────────────────────────

def _build_where_data_arr(resolved: ResolvedEntities, snapshot: bool = False) -> dict:
    """WHERE values for data_arr.
    snapshot=True: inject fiscal_month_end_date = end-of-quarter date for point-in-time snapshot.
    snapshot=False (TREND): filter by fiscal_quarter / fiscal_year only.
    """
    where: dict = {}

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

    # Snapshot: pin to the last fiscal_month_end_date of the given quarter
    if snapshot:
        fq = f.fiscal_quarter_label or (f.quarter_labels[0] if len(f.quarter_labels or []) == 1 else None)
        if fq:
            dr = _fiscal_label_to_date_range(fq)
            if dr:
                where["fiscal_month_end_date"] = dr[1]   # end of quarter = max snapshot date
        elif not f.fiscal_year_label and not f.quarter_labels:
            # No fiscal specified — default to current quarter snapshot
            fq_now = _current_fiscal_quarter()
            dr = _fiscal_label_to_date_range(fq_now)
            if dr:
                where["fiscal_month_end_date"] = dr[1]
                where["fiscal_quarter"] = fq_now

    # Product (flat columns)
    where.update(_product_where_flat(resolved.product_filter))

    # Geo — data_arr uses cfy_geo / cfy_area / cfy_region
    if resolved.geo_detail_filter:
        for gf in resolved.geo_detail_filter:
            col = gf.col   # already cfy_geo / cfy_area / cfy_region
            val = gf.value
            existing = where.get(col) or where.get(f"{col}__in")
            if existing is None:
                where[col] = val
            elif isinstance(existing, list):
                if val not in existing:
                    existing.append(val)
                    where[f"{col}__in"] = existing
                    where.pop(col, None)
            else:
                if val != existing:
                    where[f"{col}__in"] = [existing, val]
                    where.pop(col, None)
    elif len(resolved.geo_filter) == 1:
        where["cfy_geo"] = resolved.geo_filter[0]
    elif len(resolved.geo_filter) > 1:
        where["cfy_geo__in"] = resolved.geo_filter

    # Segment
    if len(resolved.segment_filter) == 1:
        where["market_segment"] = resolved.segment_filter[0]
    elif len(resolved.segment_filter) > 1:
        where["market_segment__in"] = resolved.segment_filter

    # Order type (mrr_order_type in data_arr)
    if len(resolved.order_type_filter) == 1:
        where["mrr_order_type"] = resolved.order_type_filter[0]
    elif len(resolved.order_type_filter) > 1:
        where["mrr_order_type__in"] = resolved.order_type_filter

    # Account
    af = resolved.account_filter
    if af.account_ids and len(af.account_ids) > 1:
        where["account_id__in"] = af.account_ids
    elif af.account_id and af.account_id != "__all__":
        where["account_id"] = af.account_id
    elif af.account_ids:
        where["account_id"] = af.account_ids[0]

    # SKU (item_name in data_arr)
    if len(resolved.sku_filter) == 1:
        where["item_name"] = resolved.sku_filter[0]
    elif len(resolved.sku_filter) > 1:
        where["item_name__in"] = resolved.sku_filter

    return where


# ── WHERE builder: data_acv ──────────────────────────────────────────────────

def _build_where_data_acv(resolved: ResolvedEntities) -> dict:
    """WHERE values for data_acv.
    Geo uses plain `geo` column (not cfy_geo).
    carve_split_type controls deal motion; NNACV variant auto-excludes renewals.
    """
    where: dict = {}

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

    # Product (flat columns)
    where.update(_product_where_flat(resolved.product_filter))

    # Geo — data_acv.geo column holds 'Americas', 'AMS ECE', 'AMS MPH', 'APJ', 'EMEA', etc.
    # geo_filter already expanded (Americas → ['AMS ECE', 'AMS MPH']) — works for data_acv too
    if len(resolved.geo_filter) == 1:
        where["geo"] = resolved.geo_filter[0]
    elif len(resolved.geo_filter) > 1:
        where["geo__in"] = resolved.geo_filter

    # Account
    af = resolved.account_filter
    if af.account_ids and len(af.account_ids) > 1:
        where["account_id__in"] = af.account_ids
    elif af.account_id and af.account_id != "__all__":
        where["account_id"] = af.account_id
    elif af.account_ids:
        where["account_id"] = af.account_ids[0]

    # Deal motion → carve_split_type
    # NNACV variant: exclude renewals (net new = all except renewal)
    metric_variant = resolved.metric.variant if resolved.metric else "snapshot"
    if metric_variant == "nnacv":
        where["carve_split_type__not_in"] = ["Renewal"]
    elif resolved.order_type_filter:
        # Map order_type_filter canonical values → carve_split_type values in data_acv
        # Canonical values come from schema.yaml order_type_aliases (already resolved by PhraseMatcher)
        _ot_map: dict[str, str | list[str]] = {
            # New business variants
            "New":           "New",
            "NEW_CUST":      "NEW_CUST",      # new logo / new customer
            # Cross-sell / new to product
            "NEW_L1_PRODUCT":"NEW_L1_PRODUCT",
            "NEW_L2_PRODUCT":"NEW_L2_PRODUCT",
            "NEW_L3_PRODUCT":"NEW_L3_PRODUCT",
            # Renewal / Upsell / Expansion — pass through directly
            "Renewal":       "Renewal",
            "Upsell":        "Upsell",
            "Expansion":     "Expansion",
        }
        mapped = [_ot_map.get(ot, ot) for ot in resolved.order_type_filter]
        # Flatten: if any mapped value is a list, expand it
        flat: list[str] = []
        for m in mapped:
            if isinstance(m, list):
                flat.extend(m)
            else:
                flat.append(m)
        if len(flat) == 1:
            where["carve_split_type"] = flat[0]
        else:
            where["carve_split_type__in"] = flat

    # SKU
    if len(resolved.sku_filter) == 1:
        where["sku"] = resolved.sku_filter[0]
    elif len(resolved.sku_filter) > 1:
        where["sku__in"] = resolved.sku_filter

    return where


# ── WHERE builder: data_inc_arr ──────────────────────────────────────────────

def _build_where_data_inc_arr(resolved: ResolvedEntities) -> dict:
    """WHERE values for data_inc_arr.
    ALWAYS injects aggregation_level = 'Level L3' for most accurate results.
    Uses cfy_geo / cfy_area / cfy_region (same as data_arr).
    Keyed on end_user_parent_id — no account_id filter available.
    """
    where: dict = {}

    # ALWAYS required for data_inc_arr
    where["aggregation_level"] = "Level L3"

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

    # Product (flat columns)
    where.update(_product_where_flat(resolved.product_filter))

    # Geo — data_inc_arr uses cfy_geo / cfy_area / cfy_region
    if resolved.geo_detail_filter:
        for gf in resolved.geo_detail_filter:
            col = gf.col
            val = gf.value
            existing = where.get(col) or where.get(f"{col}__in")
            if existing is None:
                where[col] = val
            elif isinstance(existing, list):
                if val not in existing:
                    existing.append(val)
                    where[f"{col}__in"] = existing
                    where.pop(col, None)
            else:
                if val != existing:
                    where[f"{col}__in"] = [existing, val]
                    where.pop(col, None)
    elif len(resolved.geo_filter) == 1:
        where["cfy_geo"] = resolved.geo_filter[0]
    elif len(resolved.geo_filter) > 1:
        where["cfy_geo__in"] = resolved.geo_filter

    # Segment
    if len(resolved.segment_filter) == 1:
        where["market_segment"] = resolved.segment_filter[0]
    elif len(resolved.segment_filter) > 1:
        where["market_segment__in"] = resolved.segment_filter

    return where


# ── WHERE builder: data_quantity ─────────────────────────────────────────────

def _build_where_data_quantity(resolved: ResolvedEntities) -> dict:
    """WHERE values for data_quantity.
    ALWAYS injects fiscal_month_m_of_quarter = 'M3' (end-of-quarter snapshot).
    No geo column — filter by account / product / fiscal only.
    """
    where: dict = {}

    # ALWAYS required for data_quantity snapshot
    where["fiscal_month_m_of_quarter"] = "M3"

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

    # Product (flat columns)
    where.update(_product_where_flat(resolved.product_filter))

    # Account
    af = resolved.account_filter
    if af.account_ids and len(af.account_ids) > 1:
        where["account_id__in"] = af.account_ids
    elif af.account_id and af.account_id != "__all__":
        where["account_id"] = af.account_id
    elif af.account_ids:
        where["account_id"] = af.account_ids[0]

    return where


# ── Schema DDL builder ────────────────────────────────────────────────────────

def _build_ddl(table: str) -> str:
    tdef = _mdl.get_table(table)
    if tdef:
        return tdef.ddl(include_tiers=(1, 2))
    return f"-- Table {table} not found in MDL catalog\nCREATE TABLE {table} ();"


# ── Aggregation strategy ──────────────────────────────────────────────────────

def _compute_aggregation(resolved: ResolvedEntities) -> Aggregation:
    intent        = resolved.extracted.intent
    has_account   = bool(resolved.account_filter.account_id or resolved.account_filter.account_ids)
    multi_product = len(resolved.product_filter) > 1
    multi_geo     = len(resolved.geo_filter) > 1 or len(resolved.geo_detail_filter) > 1

    product_level = min(max((p.deepest_level for p in resolved.product_filter), default=0), 3)
    group_account = intent not in (Intent.TREND, Intent.AGGREGATE) or has_account
    show_breakdown = intent == Intent.COMPARE or multi_product or multi_geo

    return Aggregation(
        group_by_product_level=product_level,
        group_by_account=group_account,
        show_breakdown=show_breakdown,
    )


# ── GROUP BY builders ─────────────────────────────────────────────────────────

def _build_group_by_data_arr(resolved: ResolvedEntities, agg: Aggregation) -> list[str]:
    """GROUP BY for data_arr — uses end_user_name, cfy_geo, product_l1."""
    intent = resolved.extracted.intent
    groups: list[str] = []

    if intent == Intent.TREND:
        groups = ["fiscal_year", "fiscal_quarter"]
        if len(resolved.geo_filter) > 1:
            groups.insert(0, "cfy_geo")
        if agg.group_by_product_level > 0:
            col = f"product_l{agg.group_by_product_level}"
            groups = [col] + [g for g in groups if g != col]
        if resolved.account_filter.account_id or resolved.account_filter.account_ids:
            groups = ["account_id", "end_user_name"] + [g for g in groups
                      if g not in ("account_id", "end_user_name")]

    elif intent == Intent.RANK:
        groups = ["account_id", "end_user_name"]

    elif intent in (Intent.AGGREGATE, Intent.COMPARE, Intent.DELTA, Intent.RISK, Intent.LOOKUP):
        if agg.group_by_product_level > 0:
            groups.append(f"product_l{agg.group_by_product_level}")
        if len(resolved.geo_filter) > 1:
            groups.append("cfy_geo")
        if resolved.segment_filter:
            groups.append("market_segment")
        if resolved.order_type_filter:
            groups.append("mrr_order_type")
        if agg.group_by_account:
            groups.extend(c for c in ["account_id", "end_user_name"] if c not in groups)

    return groups


def _build_group_by_data_acv(resolved: ResolvedEntities, agg: Aggregation) -> list[str]:
    """GROUP BY for data_acv — uses account_name, geo, product_l1."""
    intent = resolved.extracted.intent
    groups: list[str] = []

    if intent == Intent.TREND:
        groups = ["fiscal_year", "fiscal_quarter"]
        if agg.group_by_product_level > 0:
            col = f"product_l{agg.group_by_product_level}"
            groups = [col] + [g for g in groups if g != col]
        if resolved.account_filter.account_id or resolved.account_filter.account_ids:
            groups = ["account_id", "account_name"] + [g for g in groups
                      if g not in ("account_id", "account_name")]

    elif intent == Intent.RANK:
        groups = ["account_id", "account_name"]

    elif intent in (Intent.AGGREGATE, Intent.COMPARE, Intent.DELTA, Intent.RISK, Intent.LOOKUP):
        if agg.group_by_product_level > 0:
            groups.append(f"product_l{agg.group_by_product_level}")
        if len(resolved.geo_filter) > 1:
            groups.append("geo")
        if resolved.segment_filter:
            groups.append("fp_a_parent_industry")
        if agg.group_by_account:
            groups.extend(c for c in ["account_id", "account_name"] if c not in groups)

    return groups


def _build_group_by_data_inc_arr(resolved: ResolvedEntities, agg: Aggregation) -> list[str]:
    """GROUP BY for data_inc_arr — uses end_user_parent_id/name."""
    intent = resolved.extracted.intent
    groups: list[str] = []

    if intent == Intent.TREND:
        groups = ["fiscal_year", "fiscal_quarter"]
        if agg.group_by_product_level > 0:
            col = f"product_l{agg.group_by_product_level}"
            groups = [col] + [g for g in groups if g != col]

    elif intent == Intent.RANK:
        groups = ["end_user_parent_id", "end_user_parent_name"]

    elif intent in (Intent.AGGREGATE, Intent.COMPARE, Intent.DELTA, Intent.RISK, Intent.LOOKUP):
        if agg.group_by_product_level > 0:
            groups.append(f"product_l{agg.group_by_product_level}")
        if len(resolved.geo_filter) > 1:
            groups.append("cfy_geo")
        if resolved.segment_filter:
            groups.append("market_segment")
        if agg.group_by_account:
            groups.extend(c for c in ["end_user_parent_id", "end_user_parent_name"] if c not in groups)

    return groups


# ── SQL rules per metric family ───────────────────────────────────────────────

_DATA_ARR_RULES = """
STRICT RULES for data_arr — follow exactly:
1.  Primary table is data_arr. Do NOT add any is_latest filter — the table has no such column.
2.  Use SUM(arr) AS total_arr for the ARR metric.
3.  ALWAYS include LIMIT.
4.  fiscal_year format: 'FY 2026'. fiscal_quarter format: 'FY 2026 Q1'. NEVER use bare '2026' or 'Q1FY26'.
5.  SNAPSHOT pattern (non-TREND): fiscal_month_end_date is pre-resolved in WHERE — it pins the
    query to the last day of the requested quarter (e.g. '2026-10-31' for FY 2027 Q1).
    ALWAYS include this filter as given — do NOT remove it. Do NOT add a subquery for it.
    TREND pattern: fiscal_month_end_date is NOT in WHERE — use fiscal_quarter / fiscal_year only.
6.  Product hierarchy: use flat columns product_l1, product_l2, product_l3, product_l4, product_l5.
    - For total ARR of a product family: WHERE product_l1 = 'ZIA'
    - For a sub-product: WHERE product_l2 = 'SWG'
    - NEVER use product + level — those columns do not exist in data_arr.
7.  Geo territory: `cfy_geo` (top level), `cfy_area` (area level), `cfy_region` (region level).
    - Use the exact column from WHERE. NEVER use geo, area, region — those columns do not exist.
8.  Account: use `account_id` and `end_user_name` (display name). No JOIN needed for basic queries.
    - GROUP BY account_id; include end_user_name AS account_name in SELECT for display.
    - NEVER use account_name — that column does not exist in data_arr.
9.  Order type: filter with `mrr_order_type IN ('New', 'Renewal', 'Upsell')`.
10. WHERE values are pre-resolved — use them exactly as given. NEVER add extra filters.
11. Return ONLY the SQL — no explanation, no markdown fences.
12. Multiple values use IN (...) syntax — never multiple separate WHERE conditions.
13. For TREND queries: GROUP BY fiscal_year, fiscal_quarter to show period-over-period movement.
    Use LAG(SUM(arr)) OVER (PARTITION BY account_id ORDER BY fiscal_quarter) for QoQ delta.
14. market_segment holds segment values (Enterprise, Commercial, SMB, etc.).
15. For RANK intent: add RANK() OVER (ORDER BY SUM(arr) DESC) AS rank and pct_of_total.
""".strip()


_DATA_ACV_RULES = """
STRICT RULES for data_acv — follow exactly:
1.  Primary table is data_acv. No is_latest, no level/product+level hierarchy.
2.  Primary metric: SUM(adjusted_acv) AS total_acv.
    acv_splits is the raw/NACV pivot column — use only when explicitly requested.
3.  ALWAYS include LIMIT.
4.  fiscal_year format: 'FY 2026'. fiscal_quarter format: 'FY 2026 Q1'. NEVER use bare '2026' or 'Q1FY26'.
5.  Product hierarchy: use flat columns product_l1, product_l2, product_l3, product_l4, product_l5.
    NEVER use product + level — those columns do not exist in data_acv.
6.  Geo: use plain `geo` column. Values: 'Americas' | 'AMS ECE' | 'AMS MPH' | 'APJ' | 'EMEA'.
    NEVER use cfy_geo, cfy_area, cfy_region — those columns do not exist in data_acv.
7.  Account: use `account_id` and `account_name`. No JOIN needed.
    GROUP BY account_id; include account_name in SELECT for display.
8.  Deal motion via carve_split_type (REQUIRED filter — already in WHERE when applicable):
    - NNACV (Net New ACV): carve_split_type NOT IN ('Renewal','Renewals','RENEWAL','RENEWALS')
    - New Logo: carve_split_type = 'NEW_CUST'
    - New to Product: carve_split_type IN ('NEW_L1_PRODUCT','NEW_L2_PRODUCT','NEW_L3_PRODUCT')
    - Upsell / Expansion: carve_split_type = 'Upsell'
    - Renewal: carve_split_type = 'Renewal'
    USE ONLY what is in the pre-resolved WHERE — do NOT add carve filters not listed there.
9.  WHERE values are pre-resolved — use them exactly as given. NEVER add extra filters.
10. Return ONLY the SQL — no explanation, no markdown fences.
11. Multiple values use IN (...) syntax — never multiple separate WHERE conditions.
12. For RANK intent: add RANK() OVER (ORDER BY SUM(adjusted_acv) DESC) AS rank and pct_of_total.
13. sku and sku_l1..sku_l4 available for SKU-level breakdown.
14. ACV is a BOOKING metric — represents deal value at time of contract, not recurring balance.
""".strip()


_DATA_INC_ARR_RULES = """
STRICT RULES for data_inc_arr — follow exactly:
1.  Primary table is data_inc_arr. No is_latest column — do NOT add that filter.
2.  CRITICAL: rows are keyed on end_user_parent_id (parent account), NOT account_id.
    account_id is always NULL in this table. Always use end_user_parent_id and end_user_parent_name.
3.  aggregation_level is ALWAYS pre-set to 'Level L3' in WHERE — this is mandatory.
    NEVER change or remove this filter.
4.  Key metrics:
    - Net ARR growth:  SUM(arr_change) AS total_arr_change
    - CHURN / losses:  SUM(downsell) AS total_downsell  (always negative or zero)
    - Ending ARR:      SUM(curr_qtr_arr) AS ending_arr
    - Starting ARR:    SUM(prev_qtr_arr) AS starting_arr
    - Swap impact:     SUM(swap_impact) AS total_swap
5.  ALWAYS include LIMIT.
6.  fiscal_year format: 'FY 2026'. fiscal_quarter format: 'FY 2026 Q1'.
7.  Product hierarchy: use flat columns product_l1, product_l2, product_l3.
    NEVER use product + level — those columns do not exist in data_inc_arr.
8.  Geo: use cfy_geo, cfy_area, cfy_region (NOT geo/area/region).
    Broad geo alternative: end_user_parent_geo values are 'Americas' | 'APJ' | 'EMEA'.
9.  market_segment holds segment values (Enterprise, Commercial, SMB, etc.).
10. GROUP BY end_user_parent_id, end_user_parent_name for per-account results.
11. Return ONLY the SQL — no explanation, no markdown fences.
12. Multiple values use IN (...) syntax — never multiple separate WHERE conditions.
13. For CHURN queries: ORDER BY total_downsell ASC (most negative first = most churn).
""".strip()


_DATA_NACV_TARGET_RULES = """
STRICT RULES for data_nacv_target — follow exactly:
1.  Primary table is data_nacv_target. No is_latest, no account dimension.
    This is a product-level target/planning table only.
2.  Use SUM(target) AS total_target to aggregate targets.
3.  ALWAYS include LIMIT.
4.  fiscal_year format: 'FY 2026'. fiscal_quarter format: 'FY 2026 Q1'.
5.  Product columns are: fy27_product_l1, fy27_product_l2, fy27_product_l3.
    NEVER use product, product_l1, or level — those columns do not exist here.
6.  target_type is REQUIRED in WHERE to identify the metric. Common values:
    'ACV' — ACV target, 'ACV Actual' — actual ACV booked,
    'Inc ARR' — incremental ARR target, 'New Logo' — new logo ACV,
    'Upsell' — upsell ACV, 'New to Product' — new-to-product ACV,
    'Renewing ARR' — renewal ARR target, 'Churn' — churn target,
    'Downsell' — downsell target, 'Forecast' — forecast value,
    'Open Pipeline' — open pipeline, 'Late Stage Pipeline' — late-stage pipeline,
    'Exit ARR' — exit ARR target.
7.  GROUP BY fy27_product_l1, fy27_product_l2, fy27_product_l3, fiscal_quarter.
8.  No geo, segment, or account filters available — this table has none.
9.  Return ONLY the SQL — no explanation, no markdown fences.
10. Multiple values use IN (...) syntax — never multiple separate WHERE conditions.
""".strip()


_DATA_QUANTITY_RULES = """
STRICT RULES for data_quantity — follow exactly:
1.  Primary table is data_quantity. No is_latest, no geo column.
2.  SNAPSHOT: fiscal_month_m_of_quarter = 'M3' is ALWAYS pre-set in WHERE — do NOT remove it.
    M3 = last month of the fiscal quarter = end-of-quarter snapshot.
3.  Quantity columns (use the appropriate level):
    - product_l1_qty: total seats at L1 product level (use for most queries)
    - product_l2_qty: seats at L2 sub-product level
    - product_l3_qty: seats at L3 level
    - raw_qty:        raw SKU-level quantity (before product rollup)
    SUM(product_l1_qty) AS total_qty is the standard metric.
4.  ALWAYS include LIMIT.
5.  fiscal_year format: 'FY 2026'. fiscal_quarter format: 'FY 2026 Q1'.
6.  Product hierarchy: use flat columns product_l1, product_l2, product_l3, product_l4, product_l5.
    NEVER use product + level — those columns do not exist in data_quantity.
7.  Account: use `account_id` and `account_name`. No JOIN needed.
8.  No geo column — do NOT add any geo filter. Filter by account / product / fiscal only.
9.  WHERE values are pre-resolved — use them exactly as given. NEVER add extra filters.
10. Return ONLY the SQL — no explanation, no markdown fences.
11. Multiple values use IN (...) syntax — never multiple separate WHERE conditions.
12. For RANK intent: add RANK() OVER (ORDER BY SUM(product_l1_qty) DESC) AS rank.
""".strip()


# ── ORDER BY by intent (metric-aware) ────────────────────────────────────────

def _order_by(intent: Intent, metric_alias: str) -> str | None:
    """Return ORDER BY clause using the correct metric alias for this table."""
    if intent == Intent.TREND:
        return "fiscal_year ASC, fiscal_quarter ASC"
    if intent == Intent.LOOKUP:
        return None
    if intent == Intent.RISK:
        return f"{metric_alias} ASC"
    return f"{metric_alias} DESC"


# ── WHERE builder for data_arr geo col remapping (t6-style) ──────────────────

def _cfy_col_to_t6(col: str) -> str:
    mapping = {"cfy_geo": "geo", "cfy_area": "area", "cfy_region": "region"}
    return mapping.get(col, col)


# ── Public entry point ────────────────────────────────────────────────────────

def build_context(resolved: ResolvedEntities) -> tuple[EnrichedQuery, SQLContext]:
    """S4: deterministic assembler. Returns (EnrichedQuery, SQLContext)."""
    ext    = resolved.extracted
    metric = resolved.metric

    agg = _compute_aggregation(resolved)

    enriched = EnrichedQuery(
        intent            = ext.intent,
        account_filter    = resolved.account_filter,
        product_filter    = resolved.product_filter,
        geo_filter        = resolved.geo_filter,
        geo_detail_filter = resolved.geo_detail_filter,
        segment_filter    = resolved.segment_filter,
        order_type_filter = resolved.order_type_filter,
        sku_filter        = resolved.sku_filter,
        metric            = metric,
        aggregation       = agg,
        fiscal            = resolved.fiscal,
        operator          = ext.operator,
        missing_critical  = ext.missing_critical,
    )

    primary_table = _route_table(resolved)
    af = resolved.account_filter

    schema_ddl = _build_ddl(primary_table)

    # Route to per-family WHERE builder + SQL rules
    if primary_table == "data_arr":
        is_trend = (ext.intent == Intent.TREND)
        where_values = _build_where_data_arr(resolved, snapshot=not is_trend)
        group_by     = _build_group_by_data_arr(resolved, agg)
        rules        = _DATA_ARR_RULES
        metric_col   = "arr"

    elif primary_table == "data_acv":
        where_values = _build_where_data_acv(resolved)
        # NACV re-routed here: "new ACV by company" = exclude renewals (NNACV semantics)
        if metric.name == "NACV" and "carve_split_type__not_in" not in where_values and "carve_split_type" not in where_values:
            where_values["carve_split_type__not_in"] = ["Renewal"]
        group_by     = _build_group_by_data_acv(resolved, agg)
        rules        = _DATA_ACV_RULES
        metric_col   = "adjusted_acv"

    elif primary_table == "data_inc_arr":
        where_values = _build_where_data_inc_arr(resolved)
        group_by     = _build_group_by_data_inc_arr(resolved, agg)
        rules        = _DATA_INC_ARR_RULES
        metric_col   = "downsell" if metric.variant == "downsell" else "arr_change"

    elif primary_table == "data_nacv_target":
        where_values = {}
        if resolved.fiscal.fiscal_quarter_label:
            where_values["fiscal_quarter"] = resolved.fiscal.fiscal_quarter_label
        elif resolved.fiscal.fiscal_year_label:
            where_values["fiscal_year"] = resolved.fiscal.fiscal_year_label
        group_by     = ["fy27_product_l1", "fy27_product_l2", "fy27_product_l3", "fiscal_quarter"]
        rules        = _DATA_NACV_TARGET_RULES
        metric_col   = "target"

    elif primary_table == "data_quantity":
        where_values = _build_where_data_quantity(resolved)
        group_by     = []
        if agg.group_by_product_level > 0:
            group_by.append(f"product_l{agg.group_by_product_level}")
        if agg.group_by_account:
            group_by.extend(c for c in ["account_id", "account_name"] if c not in group_by)
        rules        = _DATA_QUANTITY_RULES
        metric_col   = "product_l1_qty"

    else:
        # Fallback (should not reach)
        where_values = _build_where_data_arr(resolved, snapshot=True)
        group_by     = _build_group_by_data_arr(resolved, agg)
        rules        = _DATA_ARR_RULES
        metric_col   = "arr"

    # Build ORDER BY using the correct metric alias for this table
    _metric_alias_map = {
        "arr":           "total_arr",
        "adjusted_acv":  "total_acv",
        "arr_change":    "total_arr_change",
        "downsell":      "total_downsell",
        "target":        "total_target",
        "product_l1_qty":"total_qty",
    }
    metric_alias = _metric_alias_map.get(metric_col, f"total_{metric_col}")
    order_by = _order_by(ext.intent, metric_alias)

    # Normalised question
    geo_parts: list[str] = []
    if resolved.geo_detail_filter:
        geo_parts = [gf.value for gf in resolved.geo_detail_filter]
    elif resolved.geo_filter:
        geo_parts = resolved.geo_filter
    geo_part = f" in {', '.join(geo_parts)}" if geo_parts else ""

    fiscal   = resolved.fiscal
    period   = fiscal.fiscal_quarter_label or fiscal.fiscal_year_label or (
        f"{fiscal.quarter_labels[0]} to {fiscal.quarter_labels[-1]}" if fiscal.quarter_labels else "")
    fq_part  = f" for {period}" if period else ""
    acct_part = f" for {af.account_name}" if af.account_name else ""
    normalized = f"{ext.raw_query.strip()}{geo_part}{fq_part}{acct_part}".strip()

    ctx = SQLContext(
        normalized_question = normalized,
        intent              = ext.intent,
        metric              = metric_col,
        metric_name         = metric.name,
        metric_variant      = metric.variant,
        metric_agg          = "SUM",
        primary_table       = primary_table,
        join_clause         = None,
        schema_ddl          = schema_ddl,
        where_values        = where_values,
        group_by            = group_by,
        order_by            = order_by,
        limit               = _row_limit(ext),
        rules               = rules,
    )

    return enriched, ctx
