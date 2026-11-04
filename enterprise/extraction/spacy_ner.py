"""Stage 1 — spaCy-powered no-training extractor wrapper.

Extracts raw entity phrases from natural language questions using
spaCy POS/DEP + PhraseMatcher (closed sets) + rapidfuzz (open-set accounts).
Reads schema.yaml directly for aliases.
"""
from __future__ import annotations

import difflib
from functools import lru_cache
import re
from typing import Any, Optional

from ner_spacy.extractor import Extractor, ExtractionResult
from pipeline.models import ExtractedQuery, Intent
from core.settings import get_schema

_QTR_TYPO = re.compile(r"\bquart(?:e?rs?|ers?|ars?|ors?)\b", re.I)


def _fix_typos(query: str) -> str:
    """'last 4 Quaters' → 'last 4 quarters': period parsers only know the correct spelling."""
    return _QTR_TYPO.sub(lambda m: "quarters" if m.group(0).lower().endswith("s") else "quarter", query)


_ANALYTICS_SIGNAL = re.compile(
    r"\barr\b|\bacv\b|\bchurn\b|\brevenue\b|\bgrowth\b|\btop\b|\bbottom\b"
    r"|\btrend\b|\bquarter\b|\bfiscal\b|\bfy\d\d\b|\bq[1-4]\b"
    r"|\baccount\b|\baccounts\b|\bcustomer\b|\bcompan(?:y|ies)\b"
    r"|\bproduct\b|\bgeo\b|\bregion\b|\bsegment\b|\bemea\b|\bapj\b|\bamer\b|\bapac\b"
    r"|\bdownsell\b|\bupsell\b|\brenewal\b|\bmetric\b|\busage\b|\bquantity\b|\bqty\b"
    r"|\brank\b|\bbreakdown\b|\bsplit\b|\bcompare\b|\bversus\b|\bvs\b|\bdelta\b|\brisk\b",
    re.I,
)

_ANALYTICS_KEYWORDS = frozenset([
    "revenue", "quarter", "fiscal", "account", "accounts", "product", "growth",
    "segment", "metric", "trend", "churn", "renewal", "upsell", "downsell",
    "quantity", "usage", "breakdown", "compare", "versus", "delta", "customer", "risk",
])


def _has_analytics_signal(query: str) -> bool:
    """True if query contains any analytics signal words."""
    if _ANALYTICS_SIGNAL.search(query):
        return True
    tokens = re.findall(r"\b\w{5,}\b", query.lower())
    for tok in tokens:
        if difflib.get_close_matches(tok, _ANALYTICS_KEYWORDS, n=1, cutoff=0.82):
            return True
    return False


_SINGULAR_RE = re.compile(
    r"\b(?:top|bottom|biggest|largest|highest|smallest|lowest|best|worst)\s+(?:single\s+|one\s+)?"
    r"(?:account|company|customer)\b"
    r"|\bwhich\s+(?:account|company|customer)\s+(?:has|is|have)\b",
    re.I,
)


def _bootstrap_known_names(limit: int = 5000) -> list[str]:
    """Bootstrap known accounts from DB or CSV for open-set matching."""
    try:
        from core.db import query_all
        rows = query_all("SELECT DISTINCT account_name FROM dim_account WHERE account_name IS NOT NULL LIMIT 5000")
        return [r["account_name"] for r in rows if r.get("account_name")]
    except Exception:
        return []


@lru_cache(maxsize=1)
def _get_extractor() -> Extractor:
    """Build the Extractor once and cache."""
    return Extractor(known_companies=_bootstrap_known_names())


def _find_cfy_phrases(text: str) -> list[str]:
    """Detect cfy_geo/cfy_area/cfy_region phrases in text."""
    from extraction.tools.geo_tool import get_geo_nodes
    nodes = get_geo_nodes()
    found: list[str] = []
    for n in sorted(nodes, key=lambda x: len(x["value"]), reverse=True):
        val = n["value"]
        if re.search(r"\b" + re.escape(val) + r"\b", text, re.IGNORECASE):
            if val not in found:
                found.append(val)
    return [v for v in found if not any(other != v and other.upper().startswith(v.upper() + " ") for other in found)]


def _scrub(d: dict[str, Any], query: str, sku_canonicals: list[str], cfy_phrases: list[str]) -> dict[str, Any]:
    def _tokens(phrase: str) -> set[str]:
        return {t.upper() for t in re.findall(r"[A-Za-z0-9]+", phrase) if t}

    sku_tokens: set[str] = set()
    for s in sku_canonicals:
        sku_tokens |= _tokens(s)
    cfy_tokens: set[str] = set()
    for c in cfy_phrases:
        cfy_tokens |= _tokens(c)

    d["products_raw"] = [
        p for p in d.get("products_raw", [])
        if p.upper() not in sku_tokens or p.upper() in {s.upper() for s in sku_canonicals}
    ]

    cfy_prefix_canons = {p.split()[0].upper() for p in cfy_phrases if " " in p}
    d["geo_raw"] = [g for g in d.get("geo_raw", []) if g.upper() not in cfy_prefix_canons]

    if d.get("account_raw"):
        a = str(d["account_raw"]).strip()
        if (
            a.upper() in sku_tokens
            or a.upper() in cfy_tokens
            or a.upper() in {s.upper() for s in sku_canonicals}
            or a.upper() in {c.upper() for c in cfy_phrases}
        ):
            d["account_raw"] = None

    return d


def extract(query: str) -> ExtractedQuery:
    """S1 Extraction: maps query string to ExtractedQuery."""
    text = _fix_typos(query)

    from extraction.tools import sku_tool
    sku_canonicals = [c for _, _, c in sku_tool.find_skus_in(text)]
    cfy_phrases = _find_cfy_phrases(text)

    def _tok_set(phrases: list[str]) -> set[str]:
        out: set[str] = set()
        for p in phrases:
            out |= {t.upper() for t in re.findall(r"[A-Za-z0-9]+", p) if t}
        return out

    sku_tokens = _tok_set(sku_canonicals)
    cfy_tokens = _tok_set(cfy_phrases)

    res = _get_extractor().extract(text)
    d = res.to_s1_dict()
    d = _scrub(d, text, sku_canonicals, cfy_phrases)

    all_accounts: list[str] = list(dict.fromkeys(
        a for grp in res.groups for a in grp.accounts
    ))
    all_accounts = [
        a for a in all_accounts
        if a.upper() not in sku_tokens
        and a.upper() not in cfy_tokens
        and a.upper() not in {s.upper() for s in sku_canonicals}
        and a.upper() not in {c.upper() for c in cfy_phrases}
    ]
    primary_account = all_accounts[0] if all_accounts else None

    # Reconcile intent
    intent_val = d.get("intent", "AGGREGATE")
    if intent_val == "LOOKUP" and not all_accounts:
        intent_val = "RANK" if d.get("operator") else "AGGREGATE"

    # Convert geo_raw to list or None
    raw_geos = d.get("geo_raw", [])
    geo_raw_val = raw_geos[0] if raw_geos else None

    raw_segments = d.get("segment_raw", [])
    segment_raw_val = raw_segments[0] if raw_segments else None

    raw_orders = d.get("order_type_raw", [])
    order_type_raw_val = raw_orders[0] if raw_orders else None

    sku_raw_val = sku_canonicals[0] if sku_canonicals else None
    geo_detail_raw_val = cfy_phrases[0] if cfy_phrases else None

    limit_val = 10
    if d.get("limit_n") is not None:
        try:
            limit_val = int(d["limit_n"])
        except Exception:
            limit_val = 10

    return ExtractedQuery(
        raw_query=d.get("raw_query", query),
        intent=Intent(intent_val),
        account_raw=primary_account,
        accounts_raw=all_accounts,
        products_raw=d.get("products_raw", []),
        geo_raw=geo_raw_val,
        segment_raw=segment_raw_val,
        order_type_raw=order_type_raw_val,
        sku_raw=sku_raw_val,
        geo_detail_raw=geo_detail_raw_val,
        metric_raw=d.get("metric_raw", "ARR"),
        fiscal_raw=d.get("fiscal_raw"),
        operator=d.get("operator"),
        limit_n=limit_val,
        missing_critical=(
            ["not_arr_query"] if not _has_analytics_signal(query) else d.get("missing_critical", [])
        ),
    )


def find_slots(query: str) -> dict[str, Any]:
    res = _get_extractor().extract(_fix_typos(query))
    g = res.primary
    return {
        "accounts": [a for grp in res.groups for a in grp.accounts],
        "products": g.products,
        "geo": g.geo,
        "segments": g.segments,
        "fiscal": g.fiscal,
    }

