"""Pydantic v2 data contracts for every pipeline stage.

Each class here represents the input/output shape of exactly one stage in
the NL-to-SQL pipeline.  Keeping contracts in one file means any agent or
utility can import without circular dependencies.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Top-level enums
# ---------------------------------------------------------------------------

class Intent(str, Enum):
    """Semantic intent of the user's question."""

    RANK      = "RANK"       # "top N accounts by ARR"
    LOOKUP    = "LOOKUP"     # "what is Acme's ARR?"
    AGGREGATE = "AGGREGATE"  # "total ARR for segment X"
    TREND     = "TREND"      # "ARR trend over last 4 quarters"
    COMPARE   = "COMPARE"    # "compare ARR for Acme vs BetaCo"
    DELTA     = "DELTA"      # "ARR change between Q1 and Q2"
    RISK      = "RISK"       # "accounts at churn risk"


ChartType = Literal["table", "bar", "line", "stat_card", "scatter"]


# ---------------------------------------------------------------------------
# Stage 1 — Extraction models
# ---------------------------------------------------------------------------

class ExtractedQuery(BaseModel):
    """Raw extraction output from the NER / rule-based extraction stage.

    All *_raw fields are the literal strings pulled from the user's text.
    Downstream resolvers convert them to typed, validated objects.
    """

    raw_query: str = Field(..., description="The original user question, unchanged.")

    # Semantic intent (may be overridden by classifier)
    intent: Intent = Field(Intent.AGGREGATE, description="Extracted intent.")

    # Raw entity strings — single or list variants as appropriate
    account_raw: Optional[str]        = Field(None, description="Single account mention.")
    accounts_raw: list[str]           = Field(default_factory=list, description="Multiple account mentions.")
    products_raw: list[str]           = Field(default_factory=list, description="Product / offering mentions.")
    geo_raw: Optional[str]            = Field(None, description="Geography mention (country, region, …).")
    segment_raw: Optional[str]        = Field(None, description="Customer segment mention.")
    order_type_raw: Optional[str]     = Field(None, description="Order-type mention (e.g. 'renewal', 'new').")
    sku_raw: Optional[str]            = Field(None, description="SKU / offering-code mention.")
    geo_detail_raw: Optional[str]     = Field(None, description="Sub-geography detail (city, state, …).")
    metric_raw: str                   = Field("ARR", description="Metric name as extracted.")

    # Fiscal
    fiscal_raw: Optional[str]         = Field(None, description="Fiscal period as extracted ('FY25 Q2', …).")
    operator: Optional[str]           = Field(None, description="Comparison operator ('>','<','between',…).")
    limit_n: int                      = Field(10, description="N for top-N queries.")

    # Quality flags
    missing_critical: list[str]       = Field(
        default_factory=list,
        description="Names of fields that are required but could not be found.",
    )

    # Resolved fiscal primitives (populated by fiscal resolver, kept here for convenience)
    fiscal_year: Optional[int]        = Field(None, description="Resolved fiscal year integer (e.g. 2025).")
    fiscal_quarter: Optional[int]     = Field(None, description="Resolved fiscal quarter integer (1-4).")


class ProductFilter(BaseModel):
    """Hierarchical product filter.  L1 → L5 mirror the product taxonomy levels."""

    l1: Optional[str] = None
    l2: Optional[str] = None
    l3: Optional[str] = None
    l4: Optional[str] = None
    l5: Optional[str] = None
    deepest_level: int = Field(0, description="Index (1-5) of the deepest populated level, 0 if none.")

    @classmethod
    def from_path(cls, path: tuple[str, ...]) -> "ProductFilter":
        """Build a ProductFilter from a tuple of level values.

        Args:
            path: Ordered strings from L1 (index 0) to at most L5 (index 4).
                  Excess values are silently ignored.

        Returns:
            Populated ProductFilter with deepest_level set.
        """
        levels = dict(zip(["l1", "l2", "l3", "l4", "l5"], path))
        deepest = len(path) if len(path) <= 5 else 5
        return cls(**levels, deepest_level=deepest)

    @property
    def path(self) -> tuple[str, ...]:
        """Return the populated hierarchy as a left-to-right tuple."""
        return tuple(
            v
            for v in (self.l1, self.l2, self.l3, self.l4, self.l5)
            if v is not None
        )


class AccountFilter(BaseModel):
    """Account resolution result for a single mention or a list of mentions."""

    account_raw: Optional[str]   = Field(None, description="Original text that triggered account lookup.")
    account_id: Optional[str]    = Field(None, description="Primary resolved account ID.")
    account_name: Optional[str]  = Field(None, description="Primary resolved account display name.")

    # Multi-account variants
    multiple: list[str]    = Field(default_factory=list, description="Raw names when multiple accounts mentioned.")
    account_ids: list[str] = Field(default_factory=list, description="Resolved IDs for the multiple list.")


class Fiscal(BaseModel):
    """Fully resolved fiscal period descriptor."""

    fy: Optional[int]              = Field(None, description="Fiscal year integer (e.g. 2025).")
    quarter: Optional[int]         = Field(None, description="Fiscal quarter integer (1–4); None for full-year.")
    is_range: bool                 = Field(False, description="True when the period spans multiple quarters.")

    # Human-readable labels (used in UI / chart titles)
    fiscal_quarter_label: Optional[str] = Field(None, description="E.g. 'Q2 FY25'.")
    fiscal_year_label: Optional[str]    = Field(None, description="E.g. 'FY25'.")
    quarter_labels: list[str]           = Field(
        default_factory=list,
        description="Ordered list of quarter labels for range queries.",
    )

    # Comparison anchor (DELTA / COMPARE)
    compare_to: Optional["Fiscal"] = Field(None, description="Second period for delta/compare intent.")


class MetricRange(BaseModel):
    """Numeric range filter applied to a metric value."""

    min: Optional[float]  = Field(None, description="Inclusive lower bound.")
    max: Optional[float]  = Field(None, description="Inclusive upper bound.")
    operator: str         = Field("between", description="SQL operator: 'between','gt','lt','gte','lte'.")


class Metric(BaseModel):
    """Fully resolved metric descriptor sourced from the MDL registry."""

    name: str               = Field("ARR", description="Canonical metric name.")
    table: str              = Field("data_arr", description="Primary fact table for this metric.")
    col: str                = Field("arr", description="Column that holds the metric value.")
    variant: str            = Field("snapshot", description="Metric variant (snapshot, cumulative, …).")
    range: Optional[MetricRange] = Field(None, description="Optional value-range filter.")


class GeoFilter(BaseModel):
    """Geography filter resolved to a known column/value pair."""

    col: str   = Field(..., description="Column name in the fact table (e.g. 'region', 'country').")
    value: str = Field(..., description="Normalised value to filter on.")


class CompanyMatch(BaseModel):
    """Single fuzzy-match candidate returned by the account resolver."""

    account_id: str              = Field(..., description="ID in the accounts master table.")
    account_name: str            = Field(..., description="Display name of the matched account.")
    score: float                 = Field(..., description="Fuzzy-match confidence score (0–1).")
    matched_raw: Optional[str]   = Field(None, description="The raw string that generated this match.")


class ResolvedEntities(BaseModel):
    """Fully resolved entity bag — the output of the entire extraction stage.

    Every downstream component (classifier, agents, SQL builder) reads from
    this model.  Nothing downstream touches raw text again.
    """

    # ---- Passthrough -------------------------------------------------------
    extracted: ExtractedQuery = Field(..., description="Original extraction output.")

    # ---- Product resolution ------------------------------------------------
    product_filter: Optional[ProductFilter]           = None
    product_ambiguous: bool                           = False
    product_candidates: list[ProductFilter]           = Field(default_factory=list)
    product_hierarchy_candidates: list[ProductFilter] = Field(default_factory=list)

    # ---- Account resolution ------------------------------------------------
    account_filter: Optional[AccountFilter]  = None
    company_matches: list[CompanyMatch]      = Field(default_factory=list)
    company_ambiguous: bool                  = False

    # ---- Fiscal resolution -------------------------------------------------
    fiscal: Optional[Fiscal] = None
    fiscal_valid: bool        = True
    fiscal_warning: Optional[str] = None

    # ---- Metric resolution -------------------------------------------------
    metric: Optional[Metric] = None

    # ---- Geo resolution ----------------------------------------------------
    geo_filter: Optional[GeoFilter]        = None
    geo_invalid: bool                      = False
    geo_detail_filter: Optional[GeoFilter] = None

    # ---- Segment / order-type / SKU ----------------------------------------
    segment_filter: Optional[str]   = None
    segment_invalid: bool           = False
    order_type_filter: Optional[str] = None
    sku_filter: Optional[str]        = None

    # ---- Quality summary ---------------------------------------------------
    ambiguities: list[str] = Field(
        default_factory=list,
        description=(
            "Tags for unresolved ambiguities that require clarification. "
            "Known values: 'company', 'fiscal', 'product_hierarchy', 'geo', 'segment'."
        ),
    )


# ---------------------------------------------------------------------------
# Classifier models — LLM brain output
# ---------------------------------------------------------------------------

class SubQuery(BaseModel):
    """One atomic question within a multi-metric user request."""

    metric: str = Field(..., description="Canonical metric name this sub-query targets.")
    question: str = Field(..., description="Rewritten question scoped to this metric.")
    id: str = Field("q1", description="Stable identifier within the containing ClassifiedQuery.")


class ClassifiedQuery(BaseModel):
    """Full classification output from the LLM brain (Haiku call).

    This model drives agent routing: each entry in ``metrics_needed`` spawns
    a MetricAgent invocation.
    """

    original_query: str = Field(..., description="The user's question verbatim.")

    # Routing
    metrics_needed: list[str] = Field(
        default_factory=lambda: ["ARR"],
        description="Ordered list of canonical metric names this question requires.",
    )
    intent: Intent = Field(Intent.AGGREGATE, description="Classified semantic intent.")

    # Follow-up handling
    is_followup: bool          = Field(False, description="True when the question references prior turns.")
    resolved_question: Optional[str] = Field(
        None,
        description="Standalone rewrite of the question (populated when is_followup=True).",
    )

    # Strategic bypass flag
    is_strategic: bool = Field(
        False,
        description=(
            "True for open-ended strategy questions (best-approach, budget, …). "
            "When True the SQL pipeline is bypassed and an LLM narrative is returned directly."
        ),
    )

    # Multi-metric decomposition
    sub_queries: list[SubQuery] = Field(default_factory=list)

    # Remaining ambiguities (after entity resolution) that the LLM spotted
    ambiguities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ensure_metrics_not_empty(self) -> "ClassifiedQuery":
        """Guard: metrics_needed must always contain at least one entry."""
        if not self.metrics_needed:
            self.metrics_needed = ["ARR"]
        return self


# ---------------------------------------------------------------------------
# Agent models
# ---------------------------------------------------------------------------

class MetricAgentRequest(BaseModel):
    """Input bundle handed to a MetricAgent.run() call.

    The metric *definition* is intentionally omitted here — agents fetch it
    from the MDL registry at runtime so the registry remains the single source
    of truth.
    """

    metric_name: str = Field(..., description="Canonical metric name, e.g. 'ARR'.")
    resolved: ResolvedEntities = Field(..., description="Fully resolved entity bag.")
    question: str = Field(..., description="The (possibly rewritten) user question for this metric.")


class SQLContext(BaseModel):
    """All information the SQL generator needs to build one metric query.

    Populated by the MetricAgent from the entity bag, MDL definition, and
    schema introspection.  The SQL generator receives *only* this model —
    it never reads from ResolvedEntities directly.
    """

    normalized_question: str = Field(..., description="Cleaned, lowercase question.")
    intent: Intent           = Field(..., description="Routing intent for this sub-query.")
    metric: str              = Field(..., description="Canonical metric name.")
    metric_name: str         = Field(..., description="Human-readable display name.")
    metric_variant: str      = Field("snapshot", description="Metric variant (snapshot, cumulative, …).")
    metric_agg: str          = Field("SUM", description="Default SQL aggregation function.")
    primary_table: str       = Field(..., description="Fact table for this metric.")
    join_clause: str         = Field("", description="Pre-built JOIN fragment, may be empty.")
    schema_ddl: str          = Field("", description="Relevant DDL excerpt for the LLM's context window.")
    where_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameterised WHERE values keyed by column name.",
    )
    group_by: list[str]      = Field(default_factory=list, description="Columns for GROUP BY.")
    order_by: str            = Field("", description="ORDER BY fragment.")
    limit: int               = Field(10, description="LIMIT value.")
    rules: str               = Field("", description="Domain rules injected into the SQL prompt.")


class GeneratedSQL(BaseModel):
    """Output of the SQL generator step."""

    sql: str = Field(..., description="The generated SQL string.")
    source: Literal["llm", "fallback", "error"] = Field(
        "llm",
        description="How the SQL was produced.",
    )
    attempts: int              = Field(1, description="Number of LLM attempts made.")
    validation_errors: list[str] = Field(
        default_factory=list,
        description="Validation errors encountered before this SQL was accepted.",
    )


class QueryResult(BaseModel):
    """Raw execution result from the SQL executor."""

    sql: str                      = Field(..., description="The SQL that was executed.")
    rows: list[dict[str, Any]]    = Field(default_factory=list)
    columns: list[str]            = Field(default_factory=list)
    row_count: int                = Field(0)
    elapsed_ms: float             = Field(0.0, description="Wall-clock execution time in milliseconds.")
    db_error: Optional[str]       = Field(None, description="Database error message, if any.")
    success: bool                 = Field(False)

    @model_validator(mode="after")
    def _sync_row_count(self) -> "QueryResult":
        """Keep row_count consistent with the actual rows list."""
        if self.row_count == 0 and self.rows:
            self.row_count = len(self.rows)
        return self


class SanityWarning(BaseModel):
    """A single data-quality or business-logic warning."""

    code: str    = Field(..., description="Machine-readable warning code, e.g. 'ZERO_RESULT'.")
    message: str = Field(..., description="Human-readable explanation.")


class MetricAgentResponse(BaseModel):
    """Full response from one MetricAgent execution."""

    metric_name: str   = Field(..., description="Canonical metric name.")
    display_name: str  = Field(..., description="Human-readable label for UI headers.")
    sql: GeneratedSQL  = Field(..., description="Generated SQL and provenance info.")
    result: QueryResult = Field(..., description="Raw query result from the database.")
    insight: str       = Field("", description="LLM-generated narrative insight.")
    sanity_warnings: list[SanityWarning] = Field(default_factory=list)
    chart_type: ChartType                = Field("table", description="Suggested chart type for the UI.")


# ---------------------------------------------------------------------------
# Top-level pipeline response
# ---------------------------------------------------------------------------

class PipelineResponse(BaseModel):
    """Final response returned by the pipeline orchestrator to the caller.

    Contains all per-metric agent responses plus a merged cross-metric insight.
    """

    question: str = Field(..., description="The original user question.")
    agent_responses: list[MetricAgentResponse] = Field(default_factory=list)
    merged_insight: str  = Field("", description="Cross-metric narrative (populated when >1 metric).")
    entities: dict[str, Any] = Field(
        default_factory=dict,
        description="Serialised resolved entity summary for the front-end.",
    )
    total_elapsed_ms: float = Field(0.0, description="End-to-end latency in milliseconds.")
