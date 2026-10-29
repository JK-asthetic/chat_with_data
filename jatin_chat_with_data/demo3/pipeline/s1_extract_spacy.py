"""Stage 1 — spaCy-powered no-training extractor.

Drop-in replacement for `pipeline.s1_extract.extract()`. Returns the same
`ExtractedQuery` so the rest of the pipeline (S2 Resolve → S7 Respond)
is unchanged.

Why this exists:
    * The regex-based S1 is tightly coupled to curated schema aliases.
    * Scales linearly with new patterns.
    * This variant uses spaCy POS/DEP + PhraseMatcher (closed sets) +
      rapidfuzz (open-set accounts) and reads schema.yaml directly, so
      adding an alias is a one-line YAML edit.

Comparison queries ("A vs B") produce an `ExtractedQuery` whose
`fiscal_raw` holds both periods (`"<A> vs <B>"`) — matches the legacy
S1 convention. The full multi-group structure is reachable via the
module-level `extract_rich(query)` call for consumers that want it.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from ner_spacy.extractor import Extractor, ExtractionResult
from pipeline.models import ExtractedQuery, Intent
from pipeline.s1_extract import _SINGULAR_RE, _has_analytics_signal  # noqa: F401


_SCHEMA_PATH = None   # defaults to demo3/config/schema.yaml inside the extractor


@lru_cache(maxsize=1)
def _get_extractor() -> Extractor:
    """Build the Extractor once. Uses core.companies.existing if available."""
    lookup = None
    try:
        from core.companies import existing
        lookup = existing
    except Exception:
        pass
    return Extractor(lookup=lookup, known_companies=_bootstrap_known_names())


def _bootstrap_known_names(limit: int = 5000) -> list[str]:
    """Pull the top-ARR accounts for fuzzy matching. Falls back to [] if no DB."""
    try:
        from core.db import query_all
        rows = query_all(
            "SELECT DISTINCT account_name FROM dim_account "
            "WHERE account_name IS NOT NULL ORDER BY arr DESC NULLS LAST LIMIT %(n)s",
            {"n": limit},
        )
        return [r["account_name"] for r in rows if r.get("account_name")]
    except Exception:
        return []


def extract_rich(query: str) -> ExtractionResult:
    """Full extractor output including comparison groups."""
    return _get_extractor().extract(query)


def extract(query: str) -> ExtractedQuery:
    """S1 drop-in: returns the legacy ExtractedQuery shape."""
    res = _get_extractor().extract(query)
    d = res.to_s1_dict()
    return ExtractedQuery(
        raw_query        = d["raw_query"],
        intent           = Intent(d["intent"]),
        account_raw      = d["account_raw"],
        products_raw     = d["products_raw"],
        geo_raw          = d["geo_raw"],
        segment_raw      = d["segment_raw"],
        order_type_raw   = d["order_type_raw"],
        metric_raw       = d["metric_raw"],
        fiscal_raw       = d["fiscal_raw"],
        fiscal_year      = d["fiscal_year"],
        fiscal_quarter   = d["fiscal_quarter"],
        operator         = d["operator"],
        limit_n          = d["limit_n"],
        missing_critical = (
            ["not_arr_query"] if not _has_analytics_signal(query) else d["missing_critical"]
        ),
    )


# Same signature as s1_extract.find_slots so S0 decomposer can swap engines.
def find_slots(query: str) -> dict:
    res = _get_extractor().extract(query)
    g = res.primary
    return {
        "accounts": [a for grp in res.groups for a in grp.accounts],
        "products": g.products,
        "geo":      g.geo,
        "segments": g.segments,
        "fiscal":   g.fiscal,
    }
