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
        "ARR is a point-in-time STOCK: rows exist only at quarter-end snapshots (one fiscal_month_end_date per fiscal_quarter). "
        "One quarter = one snapshot, so filter fiscal_quarter = 'FY 2027 Q1'. "
        "NEVER SUM arr across several quarters without GROUP BY fiscal_quarter. "
        "Dates after today are a tiny projected tail — exclude them (fiscal_month_end_date <= CURRENT_DATE) unless a future quarter is asked for. "
        "Company = end user (end_user_id / end_user_name); a customer can span several account_id values. Account lists: GROUP BY account_id with name (ARRAY_AGG(end_user_name ORDER BY arr DESC))[1] AS account_name. A single company: GROUP BY end_user_id with MAX(end_user_name) AS account_name. "
        "because one account_id can carry several end_user_name spellings). "
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
        ColumnDef("account_id", "VARCHAR", "Account identity — GROUP BY this for per-account results", tier=1),
        ColumnDef("end_user_name", "VARCHAR", "Customer (end user) name; 1:1 with end_user_id", tier=1),
        ColumnDef("end_user_id", "VARCHAR", "End-user entity id (NOT account_id). A company filter in WHERE uses this column — copy it verbatim", tier=1),
        ColumnDef("arr", "NUMERIC", "Annual Recurring Revenue", tier=1),
        ColumnDef("product_l1", "VARCHAR", "Top-level product family e.g. ZIA, ZPA", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "Fiscal quarter e.g. FY 2026 Q1", tier=1),
        ColumnDef("fiscal_year", "VARCHAR", "Fiscal year e.g. FY 2026", tier=1),
        ColumnDef("fiscal_month_end_date", "DATE", "Quarter-end snapshot date (Jan/Apr/Jul/Oct month-ends). Prefer filtering fiscal_quarter.", tier=1),
        ColumnDef("fiscal_month", "VARCHAR", "Only the quarter's LAST month exists, e.g. 'FY 2027 Q1 OCT'", tier=2),
        ColumnDef("end_date", "TIMESTAMP", "Contract end date — drives the renewal quarter", tier=1),
        ColumnDef("mrr_order_type", "VARCHAR", "Deal type: 'New' | 'Renewal' | 'Upsell'", tier=1),
        ColumnDef("end_user_parent_id", "VARCHAR", "Parent (group) company id", tier=2),
        ColumnDef("end_user_parent_name", "VARCHAR", "Parent (group) company name", tier=2),
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
        "ACV bookings, one row per deal line. Metric: SUM(adjusted_acv). FLOW metric — additive across quarters. "
        "carve_split_type is the deal motion; raw spellings vary, so ALWAYS normalise before comparing: "
        "lower(replace(replace(trim(carve_split_type),'-','_'),' ','_')). "
        "N/U ACV = New Logo (new_logo, new_cust, new_customer, newlogo) + New-to-Product (ntp, new_to_product, new_l1..l5_product, new_to_l1..l5) + Upsell; "
        "Renewal is NOT part of N/U ACV. Only a top-level `geo` column exists (no area/region/segment). "
        "Parent cut: end_user_parent_id / end_user_parent_name (parent_account_id is empty). Data ends at the last complete quarter."
    ),
    columns=[
        ColumnDef("account_id", "VARCHAR", "Salesforce account id", tier=1),
        ColumnDef("account_name", "VARCHAR", "Account name", tier=1),
        ColumnDef("end_user_id", "VARCHAR", "End-user entity id", tier=2),
        ColumnDef("end_user_parent_id", "VARCHAR", "Parent company id", tier=1),
        ColumnDef("end_user_parent_name", "VARCHAR", "Parent company name", tier=1),
        ColumnDef("adjusted_acv", "NUMERIC", "ACV after carve/adjustments — SUM(adjusted_acv)", tier=1),
        ColumnDef("carve_split_type", "VARCHAR", "Deal motion, raw spelling (normalise!)", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "e.g. 'FY 2027 Q1'", tier=1),
        ColumnDef("fiscal_year", "VARCHAR", "e.g. 'FY 2027'", tier=2),
        ColumnDef("geo", "VARCHAR", "Top-level geo only: AMS ECE | AMS MPH | EMEA | APJ | Channel | Public Sector | Americas", tier=1),
        ColumnDef("product_l1", "VARCHAR", "L1 product", tier=1),
        ColumnDef("product_l2", "VARCHAR", "L2 product", tier=1),
        ColumnDef("product_l3", "VARCHAR", "L3 product", tier=2),
        ColumnDef("product_l4", "VARCHAR", "L4 product", tier=3),
        ColumnDef("product_l5", "VARCHAR", "L5 product", tier=3),
        ColumnDef("sku", "VARCHAR", "SKU", tier=3),
    ],
)

DATA_INC_ARR = TableDef(
    name="data_inc_arr",
    description=(
        "Quarter-over-quarter ARR movement per PARENT company and product (account_id is 100% NULL — parent/product only). "
        "Every row repeats once per aggregation_level, so ALWAYS filter aggregation_level = 'Level L3' (otherwise numbers are counted 3x). "
        "FLOW metric. Churn (positive loss) = -SUM(downsell) FILTER (WHERE comment IN ('Customer Churn','ARR Churn')). "
        "Swap = SUM(swap_positive + swap_negative) over all rows. arr_change = curr_qtr_arr - prev_qtr_arr. "
        "Rows with is_merger_demerger not null are M&A moves."
    ),
    columns=[
        ColumnDef("end_user_parent_id", "VARCHAR", "Parent company id (NOT account_id)", tier=1),
        ColumnDef("end_user_parent_name", "VARCHAR", "Parent company name", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "e.g. 'FY 2027 Q1'", tier=1),
        ColumnDef("aggregation_level", "VARCHAR", "ALWAYS 'Level L3'", tier=1),
        ColumnDef("product_l1", "VARCHAR", "L1 product", tier=1),
        ColumnDef("product_l2", "VARCHAR", "L2 product", tier=2),
        ColumnDef("product_l3", "VARCHAR", "L3 product", tier=2),
        ColumnDef("arr_change", "NUMERIC", "Net ARR change in the quarter", tier=1),
        ColumnDef("downsell", "NUMERIC", "ARR lost (<= 0)", tier=1),
        ColumnDef("swap_positive", "NUMERIC", "Swap ARR in", tier=1),
        ColumnDef("swap_negative", "NUMERIC", "Swap ARR out", tier=1),
        ColumnDef("comment", "VARCHAR", "Customer Churn | ARR Churn | Swaps | No Swaps", tier=1),
        ColumnDef("is_merger_demerger", "VARCHAR", "Not null = M&A row", tier=2),
        ColumnDef("curr_qtr_arr", "NUMERIC", "ARR at quarter end", tier=2),
        ColumnDef("prev_qtr_arr", "NUMERIC", "ARR at prior quarter end", tier=2),
        ColumnDef("cfy_geo", "VARCHAR", "Top-level geo", tier=1),
        ColumnDef("cfy_area", "VARCHAR", "Area", tier=1),
        ColumnDef("cfy_region", "VARCHAR", "Region", tier=2),
        ColumnDef("market_segment", "VARCHAR", "Segment", tier=1),
    ],
)

DATA_NACV_TARGET = TableDef(
    name="data_nacv_target",
    description=(
        "NNACV plan and actuals by product and quarter (product only — no account, parent, geo or segment). "
        "Product columns are fy27_product_l1..l3 (stops at L3). Several rows share one key, so ALWAYS SUM(target) FILTER (WHERE target_type = ...). "
        "plan = ACV - Churn; actual = 'ACV Actual' - GREATEST('Churn Actual', 'Churn'); plan % = 100 * actual / NULLIF(plan, 0). "
        "target_type values include ACV, ACV Actual, Churn, Churn Actual, Swap Actual, New Logo, Upsell, New to Product, Exit ARR. "
        "Non-product nodes exist in the table: 'Federal', 'Zscaler' and a blank name. The table says 'Security for AI' where data_acv/data_arr may say 'AI Security'."
    ),
    columns=[
        ColumnDef("fy27_product_l1", "VARCHAR", "L1 product", tier=1),
        ColumnDef("fy27_product_l2", "VARCHAR", "L2 product", tier=1),
        ColumnDef("fy27_product_l3", "VARCHAR", "L3 product", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "e.g. 'FY 2027 Q1' (targets exist for future quarters too)", tier=1),
        ColumnDef("target_type", "VARCHAR", "ACV | ACV Actual | Churn | Churn Actual | Swap Actual | ...", tier=1),
        ColumnDef("target", "NUMERIC", "Value for that target_type", tier=1),
    ],
)

DATA_PIPELINE = TableDef(
    name="data_pippeline_curr",
    description=(
        "Sales pipeline per opportunity x product (table name really is 'data_pippeline_curr'). Metric: SUM(pipeline_acv). "
        "OPEN pipeline = pipeline_type_group = 'Open Pipeline' AND stage NOT IN ('6 - Closed Won','7 - Closed Lost'), summed by opp_close_qtr. "
        "Lost deals = stage = '7 - Closed Lost'. Stages 5A..5D are all 'Procurement'. "
        "Product names here are the sales taxonomy (Internet Access and Platform, Private Access, AI Security, SecOps, ZS FLEX, ...), not the ARR hierarchy. "
        "Keyed by account_id (no parent column)."
    ),
    columns=[
        ColumnDef("account_id", "VARCHAR", "Salesforce account id", tier=1),
        ColumnDef("opportunity_id", "VARCHAR", "Opportunity id", tier=1),
        ColumnDef("opportunity_name", "VARCHAR", "Opportunity name", tier=2),
        ColumnDef("stage", "VARCHAR", "'1 - Discovery & Qualification' .. '5 - Procurement' (5A-5D) | '6 - Closed Won' | '7 - Closed Lost'", tier=1),
        ColumnDef("pipeline_type_group", "VARCHAR", "'Open Pipeline' | 'Early Stage Pipeline' | 'Pushed Pipeline' | 'Lost Pipeline' | ...", tier=1),
        ColumnDef("opp_close_qtr", "VARCHAR", "Close quarter e.g. 'FY 2027 Q2'", tier=1),
        ColumnDef("close_date", "DATE", "Expected / actual close date", tier=2),
        ColumnDef("pipeline_acv", "NUMERIC", "Pipeline ACV — SUM(pipeline_acv)", tier=1),
        ColumnDef("product_l1", "VARCHAR", "Sales-taxonomy L1", tier=1),
        ColumnDef("product_l2", "VARCHAR", "Sales-taxonomy L2", tier=2),
        ColumnDef("product_l3", "VARCHAR", "Sales-taxonomy L3", tier=2),
        ColumnDef("geo", "VARCHAR", "Top-level geo", tier=1),
        ColumnDef("area", "VARCHAR", "Area", tier=1),
        ColumnDef("region", "VARCHAR", "Region", tier=2),
        ColumnDef("market_segment", "VARCHAR", "Segment", tier=1),
    ],
)

DATA_QUANTITY = TableDef(
    name="data_quantity",
    description=(
        "License / seat quantity — a MONTHLY stock (fiscal_month = first day of the month). Filter ONE month "
        "(fiscal_month = '2026-10-01' with its fiscal_quarter); a quarter means its last month. Never SUM across months "
        "without GROUP BY fiscal_month. No geo / segment / end_user column — a company is filtered through account_id."
    ),
    always_filter={},
    columns=[
        ColumnDef("account_id", "VARCHAR", "Unique account identifier", tier=1),
        ColumnDef("account_name", "VARCHAR", "Customer display name", tier=1),
        ColumnDef("fiscal_quarter", "VARCHAR", "Fiscal quarter e.g. FY 2026 Q1", tier=1),
        ColumnDef("fiscal_month", "DATE", "First day of the month, e.g. '2026-10-01' (last month of FY 2027 Q1)", tier=1),
        ColumnDef("fiscal_month_m_of_quarter", "VARCHAR", "Month in quarter: 'M1' | 'M2' | 'M3' (M3 = quarter-end month)", tier=2),
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
        "Renewal risk per account x product. ALWAYS filter max_fiscal_month_flag = 1 (latest snapshot only). "
        "Metric: SUM(renewal_arr) = renewal ARR due in renewal_qtr. Default window = the quarter two after the snapshot quarter "
        "(snapshot FY 2027 Q1 -> renewal_qtr 'FY 2027 Q3'). Product is product_rl1 (a reporting taxonomy, e.g. SWG, Firewall, Private Access). "
        "Keyed by account_id only (no name/parent column)."
    ),
    columns=[
        ColumnDef("account_id", "VARCHAR", "Salesforce account id", tier=1),
        ColumnDef("product_rl1", "VARCHAR", "Reporting product (SWG, Firewall, Private Access, ...)", tier=1),
        ColumnDef("renewal_qtr", "VARCHAR", "Quarter the renewal is due, e.g. 'FY 2027 Q3'", tier=1),
        ColumnDef("renewal_arr", "NUMERIC", "ARR up for renewal — SUM(renewal_arr)", tier=1),
        ColumnDef("max_fiscal_month_flag", "NUMERIC", "1 = latest snapshot — ALWAYS filter = 1", tier=1),
        ColumnDef("arr", "NUMERIC", "Current ARR", tier=2),
        ColumnDef("qty", "NUMERIC", "Quantity", tier=2),
        ColumnDef("account_risk_level", "VARCHAR", "Account risk level", tier=2),
        ColumnDef("product_risk_level", "VARCHAR", "Product risk level", tier=2),
        ColumnDef("risk_summary", "VARCHAR", "Risk summary text", tier=3),
    ],
)

DATA_CHURN_REASON = TableDef(
    name="data_churn_reason",
    description=(
        "Why accounts lost ARR in a quarter: account_arr_pq -> account_arr_cq, account_arr_change (negative = loss). "
        "churn_category / churn_reason / primary_competitor explain the cause. Has account and parent columns plus geo/area/region."
    ),
    columns=[
        ColumnDef("fiscal_quarter", "VARCHAR", "e.g. 'FY 2027 Q1'", tier=1),
        ColumnDef("account_id", "VARCHAR", "Account id", tier=1),
        ColumnDef("account_name", "VARCHAR", "Account name", tier=1),
        ColumnDef("end_user_parent_id", "VARCHAR", "Parent id", tier=1),
        ColumnDef("end_user_parent_name", "VARCHAR", "Parent name", tier=1),
        ColumnDef("account_arr_pq", "NUMERIC", "Account ARR prior quarter", tier=1),
        ColumnDef("account_arr_cq", "NUMERIC", "Account ARR current quarter", tier=1),
        ColumnDef("account_arr_change", "NUMERIC", "ARR change (negative = loss)", tier=1),
        ColumnDef("arr_change_bucket", "VARCHAR", "Size bucket of the change", tier=2),
        ColumnDef("churn_category", "VARCHAR", "Churn category", tier=1),
        ColumnDef("churn_reason", "VARCHAR", "Churn reason", tier=1),
        ColumnDef("primary_competitor", "VARCHAR", "Competitor the customer moved to", tier=2),
        ColumnDef("churn_severity", "VARCHAR", "Severity", tier=2),
        ColumnDef("product_l3", "VARCHAR", "Product (L3)", tier=2),
        ColumnDef("product_arr_change", "NUMERIC", "Product-level ARR change", tier=2),
        ColumnDef("geo", "VARCHAR", "Top-level geo", tier=2),
        ColumnDef("area", "VARCHAR", "Area", tier=2),
        ColumnDef("region", "VARCHAR", "Region", tier=3),
    ],
)

T3_ARR_DETAIL = TableDef(
    name="t3_arr_detail",
    description=(
        "ARR by deployment status. One row set PER LEVEL: `level` says which hierarchy level `product` is at ('L1','L2','L3'), so ALWAYS filter level. "
        "Undeployed ARR = SUM(arr) WHERE level = 'L3' AND configuration_status IS NOT NULL AND deployed_status IS NOT NULL "
        "AND lower(trim(deployed_status)) IN ('undeployed','not deployed','limited entitled'). Product only (no account/parent); geo/area/region/segment exist."
    ),
    columns=[
        ColumnDef("fiscal_quarter", "VARCHAR", "e.g. 'FY 2027 Q1'", tier=1),
        ColumnDef("product", "VARCHAR", "Product name at the row's level", tier=1),
        ColumnDef("level", "VARCHAR", "'L1' | 'L2' | 'L3' — ALWAYS filter", tier=1),
        ColumnDef("arr", "NUMERIC", "ARR", tier=1),
        ColumnDef("deployed_status", "VARCHAR", "Deployed | Underdeployed | Undeployed", tier=1),
        ColumnDef("configuration_status", "VARCHAR", "Well Configured | Base Level Configuration | Unconfigured", tier=1),
        ColumnDef("geo", "VARCHAR", "Top-level geo", tier=2),
        ColumnDef("area", "VARCHAR", "Area", tier=2),
        ColumnDef("region", "VARCHAR", "Region", tier=3),
        ColumnDef("market_segment", "VARCHAR", "Segment", tier=2),
    ],
)

CATALOG: dict[str, TableDef] = {
    "data_arr": DATA_ARR,
    "data_acv": DATA_ACV,
    "data_inc_arr": DATA_INC_ARR,
    "data_nacv_target": DATA_NACV_TARGET,
    "data_pippeline_curr": DATA_PIPELINE,
    "t3_arr_detail": T3_ARR_DETAIL,
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

