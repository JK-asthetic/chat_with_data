"""MDL (Model Definition Language) catalog — semantic layer for multi-table queries.

Each table has columns classified into 3 tiers:
  Tier 1 (always):   always injected into SQL generation prompt DDL (~5-8 cols)
  Tier 2 (semantic): injected when semantically relevant to the question (~5-10 cols)
  Tier 3 (rarely):   injected only when explicitly named by user

Tables defined:
  data_arr          — ARR snapshot/historical (all ARR queries; snapshot via fiscal_month_end_date)
  data_acv          — ACV bookings (ACV / NNACV / deal-motion queries)
  data_inc_arr      — Incremental ARR by parent account (net-new, churn, downsell)
  data_nacv_target  — NACV planning targets by product up to L3
  data_quantity     — License/seat quantity by product and fiscal month
  dim_account       — Account dimension (AE, CSM, industry attributes)
  data_renewal_risk — Account renewal risk scores and risk categories
  data_churn_reason — Customer churn reason breakdown and amounts
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ColumnDef:
    name: str
    dtype: str  # "VARCHAR" | "NUMERIC" | "DATE" | "BOOLEAN" | "INTEGER"
    description: str
    tier: int = 2  # 1=always, 2=semantic, 3=rarely
    example: Optional[str] = None


@dataclass
class JoinDef:
    """Describes how to JOIN this table's parent to a target table."""

    target: str
    on: str
    join_type: str = "LEFT"
    alias: Optional[str] = None

    def sql(self) -> str:
        alias_part = f" {self.alias}" if self.alias else ""
        return f"{self.join_type} JOIN {self.target}{alias_part} ON {self.on}"


@dataclass
class TableDef:
    name: str
    description: str
    columns: list[ColumnDef] = field(default_factory=list)
    always_filter: dict[str, str] = field(default_factory=dict)
    joins: list[JoinDef] = field(default_factory=list)

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


# ── Table Definitions ────────────────────────────────────────────────────────

DATA_ARR = TableDef(
    name="data_arr",
    description=(
        "Primary ARR table — snapshot + historical (all quarters FY2023 Q2 onwards). "
        "SNAPSHOT pattern: filter fiscal_month_end_date = MAX(fiscal_month_end_date) for the quarter. "
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
        ColumnDef("account_id", "VARCHAR", "Unique account identifier", tier=1),
        ColumnDef("end_user_name", "VARCHAR", "Customer display name (alias AS account_name in SELECT)", tier=1),
        ColumnDef("arr", "NUMERIC", "Annual Recurring Revenue", tier=1),
        ColumnDef("product_l1", "VARCHAR", "Top-level product family e.g. ZIA, ZPA", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "Fiscal quarter e.g. FY 2026 Q1", tier=1),
        ColumnDef("fiscal_year", "VARCHAR", "Fiscal year e.g. FY 2026", tier=1),
        ColumnDef("fiscal_month_end_date", "DATE", "Calendar end date of fiscal month. Snapshot filter = MAX date.", tier=1),
        ColumnDef("mrr_order_type", "VARCHAR", "Deal type: 'New' | 'Renewal' | 'Upsell'", tier=1),
        ColumnDef("cfy_geo", "VARCHAR", "Top-level geo territory", tier=2, example="EMEA"),
        ColumnDef("cfy_area", "VARCHAR", "Sub-geo area", tier=2, example="EMEA DACH"),
        ColumnDef("cfy_region", "VARCHAR", "Sub-area region", tier=2, example="Germany ENT"),
        ColumnDef("market_segment", "VARCHAR", "Customer segment: Enterprise, Commercial, SMB", tier=2),
        ColumnDef("product_l2", "VARCHAR", "L2 sub-product e.g. SWG, Firewall", tier=2),
        ColumnDef("qty", "NUMERIC", "License seat quantity", tier=2),
        ColumnDef("product_l3", "VARCHAR", "L3 product", tier=3),
        ColumnDef("contract_details_number", "VARCHAR", "Contract identifier", tier=3),
        ColumnDef("item_name", "VARCHAR", "SKU / item code", tier=3),
    ],
)

DATA_ACV = TableDef(
    name="data_acv",
    description=(
        "ACV bookings table — deal-level. "
        "Primary metric: adjusted_acv (use by default). "
        "carve_split_type: 'Expansion' | 'New' | 'NEW_CUST' (new logo) | 'NEW_L1_PRODUCT' | 'Renewal' | 'Upsell'. "
        "NNACV = ACV excluding renewals: WHERE carve_split_type NOT IN ('Renewal'). "
        "Geo stored as plain `geo` column (values: 'Americas', 'AMS ECE', 'AMS MPH', 'APJ', 'EMEA')."
    ),
    columns=[
        ColumnDef("account_id", "VARCHAR", "Unique account identifier", tier=1),
        ColumnDef("account_name", "VARCHAR", "Customer display name", tier=1),
        ColumnDef("adjusted_acv", "NUMERIC", "Primary ACV metric — SUM(adjusted_acv) AS total_acv", tier=1),
        ColumnDef("carve_split_type", "VARCHAR", "Deal motion e.g. 'NEW_CUST', 'Renewal', 'Expansion'", tier=1),
        ColumnDef("product_l1", "VARCHAR", "L1 product family e.g. ZIA, ZPA", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "Fiscal quarter e.g. FY 2026 Q1", tier=1),
        ColumnDef("fiscal_year", "VARCHAR", "Fiscal year e.g. FY 2026", tier=1),
        ColumnDef("geo", "VARCHAR", "Geo territory: 'Americas'|'AMS ECE'|'AMS MPH'|'APJ'|'EMEA'", tier=2),
        ColumnDef("product_l2", "VARCHAR", "L2 sub-product", tier=2),
        ColumnDef("sku", "VARCHAR", "Product SKU code", tier=2),
    ],
)

DATA_INC_ARR = TableDef(
    name="data_inc_arr",
    description=(
        "Incremental / delta ARR by PARENT account (end_user_parent_id). "
        "Rows are keyed on end_user_parent_id (account_id is NULL). "
        "ALWAYS filter aggregation_level = 'Level L3' for accuracy. "
        "arr_change = curr_qtr_arr - prev_qtr_arr. downsell = ARR lost (always negative or zero). "
        "CHURN queries: use SUM(downsell)."
    ),
    columns=[
        ColumnDef("end_user_parent_id", "VARCHAR", "Parent account identifier — primary key (NOT account_id)", tier=1),
        ColumnDef("end_user_parent_name", "VARCHAR", "Parent account display name", tier=1),
        ColumnDef("arr_change", "NUMERIC", "Net ARR change this quarter. Positive=growth, negative=churn", tier=1),
        ColumnDef("downsell", "NUMERIC", "Downsell / churn ARR (always negative or zero)", tier=1),
        ColumnDef("curr_qtr_arr", "NUMERIC", "ARR at end of this quarter", tier=1),
        ColumnDef("prev_qtr_arr", "NUMERIC", "ARR at end of prior quarter", tier=1),
        ColumnDef("product_l1", "VARCHAR", "L1 product family e.g. ZIA, ZPA", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "Fiscal quarter e.g. FY 2026 Q1", tier=1),
        ColumnDef("aggregation_level", "VARCHAR", "Product depth — ALWAYS filter 'Level L3'", tier=1),
        ColumnDef("cfy_geo", "VARCHAR", "Top-level geo territory", tier=2),
        ColumnDef("market_segment", "VARCHAR", "Customer segment", tier=2),
    ],
)

DATA_NACV_TARGET = TableDef(
    name="data_nacv_target",
    description=(
        "NACV targets by product and fiscal quarter. No account dimension. "
        "Product columns are prefixed fy27_: fy27_product_l1, fy27_product_l2, fy27_product_l3. "
        "target_type identifies metric: 'ACV', 'New Logo', 'Upsell', 'Churn', etc."
    ),
    columns=[
        ColumnDef("fy27_product_l1", "VARCHAR", "L1 product family target applies to e.g. ZIA, ZPA", tier=1),
        ColumnDef("fy27_product_l2", "VARCHAR", "L2 sub-product target applies to", tier=1),
        ColumnDef("fy27_product_l3", "VARCHAR", "L3 sub-product target applies to", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "Target fiscal quarter e.g. FY 2026 Q1", tier=1),
        ColumnDef("target_type", "VARCHAR", "Metric type e.g. 'ACV', 'New Logo', 'Upsell'", tier=1),
        ColumnDef("target", "NUMERIC", "Target value (SUM across products)", tier=1),
    ],
)

DATA_QUANTITY = TableDef(
    name="data_quantity",
    description=(
        "License / seat quantity table. ALWAYS filter fiscal_month_m_of_quarter = 'M3' (end-of-quarter snapshot). "
        "No geo column — filter by account_id or product only."
    ),
    always_filter={"fiscal_month_m_of_quarter": "M3"},
    columns=[
        ColumnDef("account_id", "VARCHAR", "Unique account identifier", tier=1),
        ColumnDef("account_name", "VARCHAR", "Customer display name", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "Fiscal quarter e.g. FY 2026 Q1", tier=1),
        ColumnDef("fiscal_month_m_of_quarter", "VARCHAR", "Month in quarter: ALWAYS 'M3'", tier=1),
        ColumnDef("product_l1", "VARCHAR", "L1 product family", tier=1),
        ColumnDef("product_l1_qty", "NUMERIC", "Total seat/license quantity at L1 level", tier=1),
        ColumnDef("product_l2_qty", "NUMERIC", "Quantity at L2 sub-product level", tier=1),
    ],
)

DIM_ACCOUNT = TableDef(
    name="dim_account",
    description="Account dimension. JOIN to data_arr on account_id for owner/territory attributes.",
    columns=[
        ColumnDef("account_id", "VARCHAR", "Join key to data_arr", tier=1),
        ColumnDef("account_name", "VARCHAR", "Customer name", tier=1),
        ColumnDef("ae_name", "VARCHAR", "Account Executive owner", tier=2),
        ColumnDef("csm_name", "VARCHAR", "Customer Success Manager", tier=2),
        ColumnDef("industry", "VARCHAR", "Industry vertical", tier=2),
        ColumnDef("renewal_date", "DATE", "Next renewal date", tier=2),
    ],
)

DATA_RENEWAL_RISK = TableDef(
    name="data_renewal_risk",
    description=(
        "Account renewal risk table — indicates likelihood of churn or downsell at renewal. "
        "Primary metric: renewal_risk_score (0-100, higher means greater risk). "
        "Can join with dim_account on account_id."
    ),
    columns=[
        ColumnDef("account_id", "VARCHAR", "Unique account identifier", tier=1),
        ColumnDef("account_name", "VARCHAR", "Customer display name", tier=1),
        ColumnDef("renewal_risk_score", "NUMERIC", "Risk score (0-100, higher=greater risk)", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "Fiscal quarter of renewal e.g. FY 2026 Q1", tier=1),
        ColumnDef("renewal_date", "DATE", "Scheduled renewal date", tier=2),
        ColumnDef("arr_at_risk", "NUMERIC", "ARR exposed to renewal risk", tier=2),
        ColumnDef("risk_category", "VARCHAR", "Risk tier: 'High' | 'Medium' | 'Low'", tier=2),
        ColumnDef("cfy_geo", "VARCHAR", "Geo territory e.g. EMEA, Americas", tier=2),
        ColumnDef("market_segment", "VARCHAR", "Customer segment", tier=2),
    ],
)

DATA_CHURN_REASON = TableDef(
    name="data_churn_reason",
    description=(
        "Customer churn reason breakdown — categorizes reasons for lost ARR and customer departures. "
        "Primary metric: churn_amount. Group by churn_reason for causal analysis."
    ),
    columns=[
        ColumnDef("account_id", "VARCHAR", "Unique account identifier", tier=1),
        ColumnDef("account_name", "VARCHAR", "Customer display name", tier=1),
        ColumnDef("churn_reason", "VARCHAR", "Category or cause of churn (e.g. Budget, Product, Competitor)", tier=1),
        ColumnDef("churn_amount", "NUMERIC", "Lost ARR dollar value", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "Fiscal quarter churn occurred", tier=1),
        ColumnDef("product_l1", "VARCHAR", "Product family affected", tier=2),
        ColumnDef("cfy_geo", "VARCHAR", "Geo territory", tier=2),
    ],
)

CATALOG: dict[str, TableDef] = {
    "data_arr": DATA_ARR,
    "data_acv": DATA_ACV,
    "data_inc_arr": DATA_INC_ARR,
    "data_nacv_target": DATA_NACV_TARGET,
    "data_quantity": DATA_QUANTITY,
    "dim_account": DIM_ACCOUNT,
    "data_renewal_risk": DATA_RENEWAL_RISK,
    "data_churn_reason": DATA_CHURN_REASON,
}


def get_table(name: str) -> Optional[TableDef]:
    return CATALOG.get(name)


def column_names(table: str, tiers: tuple[int, ...] = (1, 2)) -> list[str]:
    t = get_table(table)
    return [c.name for c in t.columns if c.tier in tiers] if t else []

