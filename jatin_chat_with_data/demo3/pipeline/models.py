"""Pydantic models — data contracts between pipeline stages."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class Intent(str, Enum):
    RANK      = "RANK"
    LOOKUP    = "LOOKUP"
    AGGREGATE = "AGGREGATE"
    TREND     = "TREND"
    COMPARE   = "COMPARE"
    DELTA     = "DELTA"
    RISK      = "RISK"


# ── Stage 0 — Decomposition ───────────────────────────────────────────────────

class SubQuery(BaseModel):
    """One self-contained question produced by S0. `{{qN.account}}` marks a value bound from an earlier part."""
    id:         str
    text:       str
    depends_on: list[str] = Field(default_factory=list)


class DecompositionPlan(BaseModel):
    """S0 output: what to run, in order. `passthrough` means the query was not changed."""
    original:    str
    strategy:    Literal["passthrough", "split", "followup"] = "passthrough"
    sub_queries: list[SubQuery]
    notes:       list[str] = Field(default_factory=list)   # fallbacks / guard rejections, shown in the demo
    unresolved:  list[str] = Field(default_factory=list)   # references we could not resolve -> ask the user


# ── Stage 1 — Raw Extraction (small, fast, language-only) ─────────────────────

class ExtractedQuery(BaseModel):
    """S1 output — minimal raw extraction, no enrichment, no schema knowledge."""
    raw_query:        str
    intent:           Intent
    account_raw:      Optional[str]   = None   # first / primary company name as typed
    accounts_raw:     list[str]       = Field(default_factory=list)  # all companies (multi-account queries)
    products_raw:     list[str]       = Field(default_factory=list)  # ["ZIA", "ZPA"]
    geo_raw:          list[str]       = Field(default_factory=list)  # ["EMEA", "APAC"]
    segment_raw:      list[str]       = Field(default_factory=list)  # ["Enterprise"]
    order_type_raw:   list[str]       = Field(default_factory=list)  # data_arr.mrr_order_type: ["Renewal"]
    sku_raw:          list[str]       = Field(default_factory=list)  # item_name / SKU codes as typed
    geo_detail_raw:   list[str]       = Field(default_factory=list)  # cfy hierarchy phrases as typed
    metric_raw:       str             = "ARR"
    fiscal_raw:       Optional[str]   = None   # raw: "Q1FY26", "FY26", "last quarter"
    operator:         Optional[str]   = None   # top | bottom | all
    limit_n:          Optional[int]   = None   # only an explicit 'top/bottom N'; S4 decides the default
    missing_critical: list[str]       = Field(default_factory=list)

    # Kept for main.py display compat (populated by S1 fiscal regex)
    fiscal_year:      Optional[str]   = None   # "FY 2026"
    fiscal_quarter:   Optional[str]   = None   # "FY 2026 Q1"


# ── Stage 2 — Enriched Tool Outputs ──────────────────────────────────────────

class ProductFilter(BaseModel):
    """Single product entry with full hierarchy."""
    l1:             Optional[str] = None
    l2:             Optional[str] = None
    l3:             Optional[str] = None
    l4:             Optional[str] = None
    l5:             Optional[str] = None
    deepest_level:  int           = 0   # 1=l1 known, 2=l1+l2, etc.

    @classmethod
    def from_path(cls, path: tuple[str, ...]) -> "ProductFilter":
        """Build from a hierarchy path such as ('ZIA', 'SWG', 'Core SWG')."""
        return cls(**{f"l{i}": v for i, v in enumerate(path, 1)}, deepest_level=len(path))

    @property
    def path(self) -> tuple[str, ...]:
        """The known hierarchy levels as a path, e.g. ('ZIA', 'SWG')."""
        levels = (self.l1, self.l2, self.l3, self.l4, self.l5)
        return tuple(v for v in levels[: self.deepest_level] if v)


class AccountFilter(BaseModel):
    """Resolved account(s) from Tool 2."""
    account_raw:  Optional[str]  = None
    account_id:   Optional[str]  = None
    account_name: Optional[str]  = None
    multiple:     list[str]      = Field(default_factory=list)   # display names
    account_ids:  list[str]      = Field(default_factory=list)   # DB IDs


class MetricRange(BaseModel):
    min:      Optional[float] = None
    max:      Optional[float] = None
    operator: str             = "between"  # between | gt | lt | gte | lte


class Metric(BaseModel):
    """Resolved metric from Tool 4."""
    name:    str                   = "ARR"
    table:   str                   = "data_arr"
    col:     str                   = "arr"
    variant: str                   = "snapshot"  # snapshot | delta | downsell | new_logo
    range:   Optional[MetricRange] = None


class Fiscal(BaseModel):
    """Parsed fiscal period from Tool 3."""
    fy:                   Optional[int]  = None   # 26
    quarter:              Optional[int]  = None   # 1
    is_range:             bool           = False
    fiscal_quarter_label: Optional[str]  = None   # "FY 2026 Q1" (DB format)
    fiscal_year_label:    Optional[str]  = None   # "FY 2026" (DB format)
    quarter_labels:       list[str]      = Field(default_factory=list)  # for ranges: ["FY 2025 Q3", "FY 2025 Q4", ...]
    compare_to:           Optional[str]  = None   # second period for COMPARE


class Aggregation(BaseModel):
    """Computed aggregation strategy from S4 assembler."""
    group_by_product_level: int  = 0     # 0=none, 1=l1, 2=l1+l2, ...
    group_by_account:       bool = True
    show_breakdown:         bool = False


# ── Company match (Tool 2 intermediate) ──────────────────────────────────────

class GeoFilter(BaseModel):
    """One resolved cfy geo node (col + canonical value)."""
    col:   str   # "cfy_geo" | "cfy_area" | "cfy_region"
    value: str   # canonical DB value, e.g. "Germany ENT"


class CompanyMatch(BaseModel):
    account_id:   str
    account_name: str
    score:        float
    matched_raw:  Optional[str] = None   # the raw typed name that resolved to this match


# ── Stage 2 — Resolved Entities (all 6 tool outputs) ─────────────────────────

class ResolvedEntities(BaseModel):
    """S2 output — one enriched struct per tool."""
    extracted:          ExtractedQuery

    # Tool 1 — Product Validator
    product_filter:              list[ProductFilter]                      = Field(default_factory=list)
    product_ambiguous:           bool                                     = False
    product_candidates:          dict[str, list[str]]                     = Field(default_factory=dict)
    # product phrase as typed → every hierarchy path it could mean, e.g. [["ZIA","SWG","China Premium"], ...]
    product_hierarchy_candidates: dict[str, list[list[str]]]              = Field(default_factory=dict)

    # Tool 2 — Account Resolver
    account_filter:     AccountFilter         = Field(default_factory=AccountFilter)
    company_matches:    list[CompanyMatch]    = Field(default_factory=list)
    company_ambiguous:  bool                  = False

    # Tool 3 — Fiscal Normalizer
    fiscal:             Fiscal                = Field(default_factory=Fiscal)
    fiscal_valid:       bool                  = True
    fiscal_warning:     Optional[str]         = None

    # Tool 4 — Metric Resolver
    metric:             Metric                = Field(default_factory=Metric)

    # Tool 5 — Geo Validator (simple end_user_parent_geo: Americas/APJ/EMEA)
    geo_filter:         list[str]             = Field(default_factory=list)
    geo_invalid:        list[str]             = Field(default_factory=list)
    # Tool 5b — Detailed cfy geo hierarchy
    geo_detail_filter:  list[GeoFilter]       = Field(default_factory=list)

    # Tool 6 — Segment Validator
    segment_filter:     list[str]             = Field(default_factory=list)
    segment_invalid:    list[str]             = Field(default_factory=list)

    # Order type (mrr_order_type) — canonical already, passed straight through
    order_type_filter:  list[str]             = Field(default_factory=list)

    # Tool 7 — SKU / item_name resolver
    sku_filter:         list[str]             = Field(default_factory=list)

    # Session
    session_company:    Optional[CompanyMatch] = None

    # Collected ambiguities for S3
    ambiguities:        list[str]             = Field(default_factory=list)

    # Back-compat aliases used by main.py / s3_clarify
    @property
    def company_resolved(self) -> Optional[CompanyMatch]:
        if self.account_filter.account_id and self.account_filter.account_id != "__all__":
            return CompanyMatch(
                account_id=self.account_filter.account_id,
                account_name=self.account_filter.account_name or "",
                score=1.0,
            )
        return None

    @property
    def geo_canonical(self) -> Optional[str]:
        return self.geo_filter[0] if len(self.geo_filter) == 1 else None

    @property
    def geo_ambiguous(self) -> bool:
        return bool(self.geo_invalid)


# ── Stage 4 — Enriched Query (assembled JSON for display/audit) ──────────────

class EnrichedQuery(BaseModel):
    """S4 assembled output — the canonical enriched JSON."""
    intent:            Intent
    account_filter:    AccountFilter
    product_filter:    list[ProductFilter]
    geo_filter:        list[str]             # simple end_user_parent_geo values
    geo_detail_filter: list[GeoFilter]       = Field(default_factory=list)  # cfy hierarchy
    segment_filter:    list[str]
    order_type_filter: list[str]             = Field(default_factory=list)
    sku_filter:        list[str]             = Field(default_factory=list)
    metric:         Metric
    aggregation:    Aggregation
    fiscal:         Fiscal
    operator:       Optional[str]  = None
    missing_critical: list[str]   = Field(default_factory=list)


# ── Stage 4 — SQL Context (drives S5 SQL generation) ─────────────────────────

class SQLContext(BaseModel):
    normalized_question: str
    intent:              Intent
    metric:              str       = "arr"        # DB column name
    metric_name:         str       = "ARR"        # logical name: ARR | CHURN | INCR_ARR | ACV
    metric_variant:      str       = "snapshot"   # snapshot | delta | downsell | new_logo
    metric_agg:          str       = "SUM"
    primary_table:       str       = "data_arr"
    join_clause:         Optional[str] = None
    schema_ddl:          str
    where_values:        dict[str, Any]   = Field(default_factory=dict)
    group_by:            list[str]        = Field(default_factory=list)
    order_by:            Optional[str]    = None
    limit:               int              = 10
    rules:               str              = ""


# ── Stage 5 — SQL Generation ──────────────────────────────────────────────────

class GeneratedSQL(BaseModel):
    sql:               str
    source:            Literal["llm", "fallback", "error"]
    attempts:          int       = 1
    validation_errors: list[str] = Field(default_factory=list)


# ── Stage 6 — Execution ───────────────────────────────────────────────────────

class QueryResult(BaseModel):
    sql:        str
    rows:       list[dict[str, Any]] = Field(default_factory=list)
    columns:    list[str]            = Field(default_factory=list)
    row_count:  int                  = 0
    elapsed_ms: float                = 0.0
    db_error:   Optional[str]        = None
    success:    bool                 = False


# ── Stage 7 — Response ────────────────────────────────────────────────────────

class SanityWarning(BaseModel):
    code:    str
    message: str


class PipelineResponse(BaseModel):
    question:        str
    context:         SQLContext
    generated:       GeneratedSQL
    result:          QueryResult
    sanity_warnings: list[SanityWarning] = Field(default_factory=list)
    insight:         str                 = ""
    chart_type:      Literal["table", "bar", "line", "stat_card", "scatter"] = "table"
    entities:        dict[str, Any]      = Field(default_factory=dict)  # resolved entities, saved to session memory
