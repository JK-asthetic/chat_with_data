"""Output shape of the extractor.

A query can describe one or several *entity groups* — a comparison query
"ARR in EMEA 2026 vs AMER 2027" has two groups, each with its own geo /
fiscal filters, while sharing the metric and intent.

The extractor always returns a `ExtractionResult`. Single-group queries
get one `EntityGroup`; comparisons get two or more. A `.to_s1_dict()`
helper produces the legacy flat shape the existing demo3 pipeline
(pipeline/s1_extract.py `ExtractedQuery`) expects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EntityGroup:
    """One self-contained set of filters.

    All fields hold *canonical* values (what the DB stores), not the raw
    phrase. The literal span the user typed is recorded in `evidence`
    for display / debug.
    """
    accounts: list[str]         = field(default_factory=list)   # account names
    products: list[str]         = field(default_factory=list)   # canonical product_l1
    geo:      list[str]         = field(default_factory=list)   # canonical geo (Americas/APJ/EMEA)
    segments: list[str]         = field(default_factory=list)   # canonical segment
    order_types: list[str]      = field(default_factory=list)   # data_arr.mrr_order_type: Renewal/Upsell/New
    fiscal:   Optional[str]     = None                           # raw period as typed
    fiscal_year:    Optional[str] = None                         # "FY 2026"
    fiscal_quarter: Optional[str] = None                         # "FY 2026 Q1"
    evidence: dict[str, list[str]] = field(default_factory=dict) # label -> literal spans typed


@dataclass
class ExtractionResult:
    """Full extractor output. Multi-group when the query is a comparison."""
    query:    str
    intent:   str                                                # RANK|LOOKUP|AGGREGATE|TREND|COMPARE|DELTA|RISK
    metric:   str                                                # ARR|ACV|NNACV|NACV|CHURN|INCR_ARR|QTY
    operator: Optional[str]       = None                         # top|bottom
    limit_n:  Optional[int]       = None                         # explicit N for top/bottom
    groups:   list[EntityGroup]   = field(default_factory=list)

    @property
    def is_comparison(self) -> bool:
        return len(self.groups) > 1

    @property
    def primary(self) -> EntityGroup:
        """Group[0] — for consumers that need a single flat view."""
        return self.groups[0] if self.groups else EntityGroup()

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "intent": self.intent,
            "metric": self.metric,
            "operator": self.operator,
            "limit_n": self.limit_n,
            "is_comparison": self.is_comparison,
            "groups": [
                {
                    "accounts": g.accounts, "products": g.products,
                    "geo": g.geo, "segments": g.segments, "order_types": g.order_types,
                    "fiscal": g.fiscal, "fiscal_year": g.fiscal_year,
                    "fiscal_quarter": g.fiscal_quarter,
                    "evidence": g.evidence,
                }
                for g in self.groups
            ],
        }

    def to_s1_dict(self) -> dict:
        """Flat shape compatible with pipeline.models.ExtractedQuery.

        Unions products / geo / segments across groups so no side of a
        comparison is lost; distinct periods are joined as "A vs B".
        """
        g = self.primary

        def union(field: str) -> list[str]:
            return list(dict.fromkeys(v for grp in self.groups for v in getattr(grp, field)))

        periods = list(dict.fromkeys(grp.fiscal for grp in self.groups if grp.fiscal))
        fiscal_raw = " vs ".join(periods) or None
        return {
            "raw_query": self.query,
            "intent": self.intent,
            "account_raw": g.accounts[0] if g.accounts else None,
            "products_raw": union("products"),
            "geo_raw": union("geo"),
            "segment_raw": union("segments"),
            "order_type_raw": union("order_types"),
            "metric_raw": self.metric,
            "fiscal_raw": fiscal_raw,
            "fiscal_year": g.fiscal_year,
            "fiscal_quarter": g.fiscal_quarter,
            "operator": self.operator,
            "limit_n": self.limit_n,
            "missing_critical": [],
        }
