"""
MDL (Model Definition Language) catalog — semantic layer for multi-table queries.

Each table has columns classified into 3 tiers:
  Tier 1 (always):   always injected into S5 prompt DDL (~5-8 cols)
  Tier 2 (semantic): injected when semantically relevant to the question (~5-10 cols)
  Tier 3 (rarely):   injected only when explicitly named by user (rest)

Tables defined:
  data_arr         — ARR snapshot/historical (all ARR queries; snapshot via fiscal_month_end_date)
  data_acv         — ACV bookings (ACV / NNACV / deal-motion queries)
  data_inc_arr     — Incremental ARR by parent account (net-new, churn, downsell)
  data_nacv_target — NACV planning targets by product up to L3
  data_quantity    — License/seat quantity by product and fiscal month
  dim_account      — Account dimension (AE, CSM, industry attributes)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ColumnDef:
    name:        str
    dtype:       str                 # "VARCHAR" | "NUMERIC" | "DATE" | "BOOLEAN" | "INTEGER"
    description: str
    tier:        int = 2             # 1=always, 2=semantic, 3=rarely
    example:     Optional[str] = None


@dataclass
class JoinDef:
    """Describes how to JOIN this table's parent to a target table."""
    target:    str        # target table name, e.g. "dim_account"
    on:        str        # full ON clause
    join_type: str = "LEFT"
    alias:     Optional[str] = None

    def sql(self) -> str:
        alias_part = f" {self.alias}" if self.alias else ""
        return f"{self.join_type} JOIN {self.target}{alias_part} ON {self.on}"


@dataclass
class TableDef:
    name:          str
    description:   str
    columns:       list[ColumnDef] = field(default_factory=list)
    always_filter: dict[str, str]  = field(default_factory=dict)
    joins:         list[JoinDef]   = field(default_factory=list)

    def tier1_cols(self) -> list[ColumnDef]:
        return [c for c in self.columns if c.tier == 1]

    def tier2_cols(self) -> list[ColumnDef]:
        return [c for c in self.columns if c.tier == 2]

    def get_join(self, target: str) -> Optional[JoinDef]:
        return next((j for j in self.joins if j.target == target), None)

    def ddl(self, include_tiers: tuple[int, ...] = (1, 2)) -> str:
        cols = [c for c in self.columns if c.tier in include_tiers]
        lines = [f"-- {self.description}"]
        if self.always_filter:
            af = ", ".join(f"{k}={v}" for k, v in self.always_filter.items())
            lines.append(f"-- Always filter: {af}")
        if self.joins:
            join_targets = ", ".join(j.target for j in self.joins)
            lines.append(f"-- Joinable to: {join_targets}")
        lines.append(f"CREATE TABLE {self.name} (")
        col_lines = []
        for c in cols:
            desc = f"  -- {c.description}" + (f" e.g. {c.example}" if c.example else "")
            col_lines.append(f"    {c.name} {c.dtype}{desc}")
        lines.append(",\n".join(col_lines))
        lines.append(");")
        return "\n".join(lines)


# ── Table definitions ─────────────────────────────────────────────────────────

DATA_ARR = TableDef(
    name="data_arr",
    description=(
        "Primary ARR table — snapshot + historical (all quarters FY2023 Q2 onwards). "
        "SNAPSHOT pattern: filter fiscal_month_end_date = MAX(fiscal_month_end_date) for the quarter "
        "(e.g. '2026-10-31' for FY2027 Q1). "
        "TREND pattern: omit fiscal_month_end_date and filter by fiscal_quarter or fiscal_year. "
        "Product stored as flat columns product_l1..product_l5 (NOT product+level). "
        "Geo stored as cfy_geo / cfy_area / cfy_region (NOT geo/area/region). "
        "Account display name is end_user_name (NOT account_name). "
        "No is_latest column — do NOT add that filter."
    ),
    always_filter={},
    joins=[
        JoinDef(
            target="dim_account",
            on="data_arr.account_id = dim_account.account_id",
            join_type="LEFT",
            alias="d",
        )
    ],
    columns=[
        # Tier 1 — always in prompt
        ColumnDef("account_id",          "VARCHAR", "Unique account identifier", tier=1),
        ColumnDef("end_user_name",        "VARCHAR", "Customer display name (alias AS account_name in SELECT)", tier=1),
        ColumnDef("arr",                  "NUMERIC", "Annual Recurring Revenue", tier=1),
        ColumnDef("product_l1",           "VARCHAR", "Top-level product family e.g. ZIA, ZPA", tier=1),
        ColumnDef("fiscal_quarter",       "VARCHAR", "Fiscal quarter e.g. FY 2027 Q1", tier=1),
        ColumnDef("fiscal_year",          "VARCHAR", "Fiscal year e.g. FY 2027", tier=1),
        ColumnDef("fiscal_month_end_date","DATE",    "Calendar end date of fiscal month. Snapshot: filter = MAX for the quarter e.g. '2026-10-31'", tier=1),
        ColumnDef("mrr_order_type",       "VARCHAR", "Deal type: 'New' | 'Renewal' | 'Upsell'", tier=1),
        # Tier 2 — semantic
        ColumnDef("cfy_geo",        "VARCHAR", "Top-level geo territory", tier=2, example="EMEA"),
        ColumnDef("cfy_area",       "VARCHAR", "Sub-geo area", tier=2, example="EMEA DACH"),
        ColumnDef("cfy_region",     "VARCHAR", "Sub-area region", tier=2, example="Germany ENT"),
        ColumnDef("market_segment", "VARCHAR", "Customer segment: Enterprise, Commercial, SMB", tier=2),
        ColumnDef("product_l2",     "VARCHAR", "L2 sub-product e.g. SWG, Firewall", tier=2),
        ColumnDef("qty",            "NUMERIC", "License seat quantity", tier=2),
        # Tier 3 — rarely needed
        ColumnDef("product_l3",              "VARCHAR", "L3 product", tier=3),
        ColumnDef("product_l4",              "VARCHAR", "L4 product", tier=3),
        ColumnDef("product_l5",              "VARCHAR", "L5 product", tier=3),
        ColumnDef("contract_details_number", "VARCHAR", "Contract / order identifier", tier=3),
        ColumnDef("item_name",               "VARCHAR", "SKU / item code", tier=3),
        ColumnDef("fiscal_month",            "VARCHAR", "Fiscal month label", tier=3),
        ColumnDef("sales_order_date",        "DATE",    "Date the order was booked", tier=3),
    ],
)


DATA_ACV = TableDef(
    name="data_acv",
    description=(
        "ACV (Annual Contract Value) bookings table — deal-level, 16 quarters FY2023 Q2 onwards. "
        "Primary metric: adjusted_acv (use by default). acv_splits for raw/NACV pivot. "
        "carve_split_type classifies deal motion: "
        "'Expansion' | 'New' | 'NEW_CUST' (new logo) | 'NEW_L1_PRODUCT'..'NEW_L5_PRODUCT' (new to product) | "
        "'Renewal' | 'Upsell'. "
        "NNACV = ACV excluding renewals: WHERE carve_split_type NOT IN ('Renewal'). "
        "New Logo ACV: WHERE carve_split_type = 'NEW_CUST'. "
        "New to Product: WHERE carve_split_type IN ('NEW_L1_PRODUCT','NEW_L2_PRODUCT','NEW_L3_PRODUCT'). "
        "Geo stored as plain `geo` column (values: 'Americas', 'AMS ECE', 'AMS MPH', 'APJ', 'EMEA'). "
        "No is_latest column — do NOT add that filter. No level/product+level hierarchy."
    ),
    always_filter={},
    joins=[],
    columns=[
        # Tier 1 — always in prompt
        ColumnDef("account_id",       "VARCHAR", "Unique account identifier", tier=1),
        ColumnDef("account_name",     "VARCHAR", "Customer display name", tier=1),
        ColumnDef("adjusted_acv",     "NUMERIC", "Primary ACV metric — use SUM(adjusted_acv) AS total_acv", tier=1),
        ColumnDef("carve_split_type", "VARCHAR",
                  "Deal motion: 'Expansion'|'New'|'NEW_CUST'|'NEW_L1_PRODUCT'..'NEW_L5_PRODUCT'|'Renewal'|'Upsell'",
                  tier=1),
        ColumnDef("product_l1",       "VARCHAR", "L1 product family e.g. ZIA, ZPA", tier=1),
        ColumnDef("fiscal_quarter",   "VARCHAR", "Fiscal quarter e.g. FY 2027 Q1", tier=1),
        ColumnDef("fiscal_year",      "VARCHAR", "Fiscal year e.g. FY 2027", tier=1),
        # Tier 2 — semantic
        ColumnDef("geo",              "VARCHAR", "Geo territory: 'Americas'|'AMS ECE'|'AMS MPH'|'APJ'|'EMEA'", tier=2),
        ColumnDef("sku_split_type",   "VARCHAR", "SKU-level deal motion (same values as carve_split_type)", tier=2),
        ColumnDef("product_l2",       "VARCHAR", "L2 sub-product", tier=2),
        ColumnDef("product_l3",       "VARCHAR", "L3 sub-product", tier=2),
        ColumnDef("acv_splits",       "NUMERIC", "Raw ACV before carve adjustments (NACV pivot use)", tier=2),
        ColumnDef("sku",              "VARCHAR", "Product SKU code", tier=2),
        ColumnDef("sku_l1",           "VARCHAR", "L1 SKU family", tier=2),
        # Tier 3 — rarely needed
        ColumnDef("product_l4",              "VARCHAR", "L4 product", tier=3),
        ColumnDef("product_l5",              "VARCHAR", "L5 product", tier=3),
        ColumnDef("contract_details_number", "VARCHAR", "Contract / order identifier", tier=3),
        ColumnDef("order_date",              "DATE",    "Order booking date", tier=3),
        ColumnDef("fp_a_parent_industry",    "VARCHAR", "Industry vertical of parent account", tier=3),
        ColumnDef("acv_carve",               "NUMERIC", "ACV carve adjustment component", tier=3),
        ColumnDef("adjustments",             "NUMERIC", "Manual ACV adjustments", tier=3),
        ColumnDef("contract_acv",            "NUMERIC", "Raw contract ACV before splits", tier=3),
        ColumnDef("fiscal_quarter_end_date", "DATE",    "Calendar end date of fiscal quarter", tier=3),
    ],
)


DATA_INC_ARR = TableDef(
    name="data_inc_arr",
    description=(
        "Incremental / delta ARR by PARENT account (end_user_parent_id), product, and fiscal quarter. "
        "33 quarters of history (FY2023 Q2 onwards). "
        "Key insight: rows are keyed on end_user_parent_id NOT account_id — "
        "use end_user_parent_id for joins and filters. account_id is always NULL. "
        "aggregation_level controls product depth: 'Level L1' | 'Level L2' | 'Level L3'. "
        "ALWAYS filter aggregation_level = 'Level L3' for most accurate results. "
        "arr_change = curr_qtr_arr - prev_qtr_arr (positive=growth, negative=churn/downsell). "
        "downsell = ARR lost (always negative or zero). "
        "CHURN queries: use SUM(downsell) — always negative, represents ARR lost. "
        "Geo stored as cfy_geo / cfy_area / cfy_region (NOT geo/area/region). "
        "No is_latest column."
    ),
    always_filter={},
    joins=[],
    columns=[
        # Tier 1 — always in prompt
        ColumnDef("end_user_parent_id",   "VARCHAR", "Parent account identifier — primary key (NOT account_id)", tier=1),
        ColumnDef("end_user_parent_name", "VARCHAR", "Parent account display name", tier=1),
        ColumnDef("arr_change",           "NUMERIC", "Net ARR change this quarter (curr - prev). Positive=growth, negative=churn", tier=1),
        ColumnDef("downsell",             "NUMERIC", "Downsell / churn ARR (always negative or zero)", tier=1),
        ColumnDef("curr_qtr_arr",         "NUMERIC", "ARR at end of this quarter", tier=1),
        ColumnDef("prev_qtr_arr",         "NUMERIC", "ARR at end of prior quarter", tier=1),
        ColumnDef("product_l1",           "VARCHAR", "L1 product family e.g. ZIA, ZPA", tier=1),
        ColumnDef("fiscal_quarter",       "VARCHAR", "Fiscal quarter e.g. FY 2027 Q1", tier=1),
        ColumnDef("aggregation_level",    "VARCHAR", "Product depth: 'Level L1' | 'Level L2' | 'Level L3' — ALWAYS filter 'Level L3'", tier=1),
        # Tier 2 — semantic
        ColumnDef("swap_impact",          "NUMERIC", "Net ARR impact of product swaps", tier=2),
        ColumnDef("swap_positive",        "NUMERIC", "ARR gained from product swaps", tier=2),
        ColumnDef("swap_negative",        "NUMERIC", "ARR lost from product swaps", tier=2),
        ColumnDef("cfy_geo",              "VARCHAR", "Top-level geo territory", tier=2, example="EMEA"),
        ColumnDef("cfy_area",             "VARCHAR", "Sub-geo area", tier=2, example="EMEA DACH"),
        ColumnDef("cfy_region",           "VARCHAR", "Sub-area region", tier=2, example="Germany ENT"),
        ColumnDef("end_user_parent_geo",  "VARCHAR", "Broad geo: Americas | APJ | EMEA", tier=2),
        ColumnDef("market_segment",       "VARCHAR", "Customer segment: Enterprise, Commercial, SMB", tier=2),
        ColumnDef("product_l2",           "VARCHAR", "L2 sub-product", tier=2),
        # Tier 3 — rarely needed
        ColumnDef("product_l3",              "VARCHAR", "L3 sub-product", tier=3),
        ColumnDef("fiscal_quarter_end_date", "DATE",    "Calendar date of fiscal quarter end", tier=3),
        ColumnDef("fp_a_parent_industry",    "VARCHAR", "Industry vertical of parent account", tier=3),
        ColumnDef("product_4_pillar",        "VARCHAR", "4-pillar product grouping", tier=3),
        ColumnDef("product_8_pillar",        "VARCHAR", "8-pillar product grouping", tier=3),
    ],
)


DATA_NACV_TARGET = TableDef(
    name="data_nacv_target",
    description=(
        "NACV (New ACV) targets by product (up to L3) and fiscal quarter. "
        "25 quarters of data (FY2022 Q1 – FY2028 Q1). "
        "No account dimension — this is a product-level target/planning table only. "
        "Product columns are prefixed fy27_: fy27_product_l1, fy27_product_l2, fy27_product_l3. "
        "target_type identifies the metric: 'ACV' | 'ACV Actual' | 'Inc ARR' | 'New Logo' | "
        "'Upsell' | 'New to Product' | 'Renewing ARR' | 'Churn' | 'Downsell' | "
        "'Forecast' | 'Open Pipeline' | 'Late Stage Pipeline' | 'Exit ARR' etc. "
        "Use SUM(target) grouped by product and fiscal_quarter."
    ),
    always_filter={},
    joins=[],
    columns=[
        ColumnDef("fy27_product_l1", "VARCHAR", "L1 product family target applies to e.g. ZIA, ZPA", tier=1),
        ColumnDef("fy27_product_l2", "VARCHAR", "L2 sub-product target applies to", tier=1),
        ColumnDef("fy27_product_l3", "VARCHAR", "L3 sub-product target applies to", tier=1),
        ColumnDef("fiscal_quarter",  "VARCHAR", "Target fiscal quarter e.g. FY 2027 Q1", tier=1),
        ColumnDef("target_type",     "VARCHAR",
                  "Metric type: 'ACV'|'ACV Actual'|'Inc ARR'|'New Logo'|'Upsell'|'New to Product'|"
                  "'Renewing ARR'|'Churn'|'Downsell'|'Forecast'|'Open Pipeline'|'Late Stage Pipeline'|"
                  "'Exit ARR'|'Gross Churn'|'Net Churn'|'Swap Positive'|'Swap Negative'", tier=1),
        ColumnDef("target",          "NUMERIC", "Target value (SUM to aggregate across products)", tier=1),
    ],
)


DATA_QUANTITY = TableDef(
    name="data_quantity",
    description=(
        "License / seat quantity table — 16 quarters, 3 months per quarter (M1/M2/M3). "
        "SNAPSHOT pattern: ALWAYS filter fiscal_month_m_of_quarter = 'M3' (end-of-quarter snapshot). "
        "Product stored as flat columns product_l1..product_l5. "
        "Quantity columns: product_l1_qty (L1 total), product_l2_qty, product_l3_qty, raw_qty (raw SKU). "
        "No geo column — filter by account_id or product only. "
        "No is_latest column — do NOT add that filter. "
        "For cross-product scope: use a CTE anchored to data_arr or data_acv scope, "
        "then JOIN data_quantity ON account_id + product_l1 to prevent cross-product leakage."
    ),
    always_filter={"fiscal_month_m_of_quarter": "M3"},
    joins=[],
    columns=[
        # Tier 1 — always in prompt
        ColumnDef("account_id",              "VARCHAR", "Unique account identifier", tier=1),
        ColumnDef("account_name",            "VARCHAR", "Customer display name", tier=1),
        ColumnDef("fiscal_quarter",          "VARCHAR", "Fiscal quarter e.g. FY 2027 Q1", tier=1),
        ColumnDef("fiscal_month_m_of_quarter","VARCHAR","Month within quarter: 'M1'|'M2'|'M3'. ALWAYS filter M3 for end-of-quarter snapshot.", tier=1),
        ColumnDef("product_l1",              "VARCHAR", "L1 product family e.g. ZIA, ZPA", tier=1),
        ColumnDef("product_l1_qty",          "NUMERIC", "Total seat/license quantity at L1 level (use for most queries)", tier=1),
        ColumnDef("product_l2_qty",          "NUMERIC", "Quantity at L2 sub-product level", tier=1),
        # Tier 2 — semantic
        ColumnDef("product_l2",             "VARCHAR", "L2 sub-product", tier=2),
        ColumnDef("product_l3",             "VARCHAR", "L3 sub-product", tier=2),
        ColumnDef("product_l3_qty",         "NUMERIC", "Quantity at L3 sub-product level", tier=2),
        ColumnDef("raw_qty",                "NUMERIC", "Raw SKU-level quantity (before product rollup)", tier=2),
        ColumnDef("sku",                    "VARCHAR", "Product SKU code", tier=2),
        ColumnDef("sku_l1",                 "VARCHAR", "L1 SKU family", tier=2),
        # Tier 3 — rarely needed
        ColumnDef("product_l4",             "VARCHAR", "L4 product", tier=3),
        ColumnDef("product_l5",             "VARCHAR", "L5 product", tier=3),
        ColumnDef("product_l4_qty",         "NUMERIC", "Quantity at L4 level", tier=3),
        ColumnDef("product_l5_qty",         "NUMERIC", "Quantity at L5 level", tier=3),
        ColumnDef("sku_l2",                 "VARCHAR", "L2 SKU", tier=3),
        ColumnDef("sku_l3",                 "VARCHAR", "L3 SKU", tier=3),
        ColumnDef("sku_variant",            "VARCHAR", "SKU variant code", tier=3),
        ColumnDef("raw_sku",                "VARCHAR", "Raw SKU identifier", tier=3),
        ColumnDef("fiscal_month",           "DATE",    "Fiscal month date", tier=3),
    ],
)


DIM_ACCOUNT = TableDef(
    name="dim_account",
    description="Account dimension. JOIN to data_arr on account_id for owner/territory attributes.",
    columns=[
        ColumnDef("account_id",   "VARCHAR", "Join key to data_arr", tier=1),
        ColumnDef("account_name", "VARCHAR", "Customer name", tier=1),
        ColumnDef("ae_name",      "VARCHAR", "Account Executive owner", tier=2),
        ColumnDef("csm_name",     "VARCHAR", "Customer Success Manager", tier=2),
        ColumnDef("industry",     "VARCHAR", "Industry vertical", tier=2),
        ColumnDef("renewal_date", "DATE",    "Next renewal date", tier=2),
    ],
)


# Registry — add new tables here as they are onboarded
CATALOG: dict[str, TableDef] = {
    "data_arr":         DATA_ARR,
    "data_acv":         DATA_ACV,
    "data_inc_arr":     DATA_INC_ARR,
    "data_nacv_target": DATA_NACV_TARGET,
    "data_quantity":    DATA_QUANTITY,
    "dim_account":      DIM_ACCOUNT,
}


def get_table(name: str) -> Optional[TableDef]:
    return CATALOG.get(name)


def column_names(table: str, tiers: tuple[int, ...] = (1, 2)) -> list[str]:
    t = get_table(table)
    return [c.name for c in t.columns if c.tier in tiers] if t else []
