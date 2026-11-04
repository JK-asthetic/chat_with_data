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

import re
from functools import lru_cache
from typing import Optional

from core import skus as _skus
from core.geo import get_geo_nodes
from ner_spacy.extractor import Extractor, ExtractionResult
from pipeline.models import ExtractedQuery, Intent

# ── Helpers previously in s1_extract (now inlined here) ──────────────────────

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
    r"|\brank\b|\bbreakdown\b|\bsplit\b|\bcompare\b|\bversus\b|\bvs\b|\bdelta\b",
    re.I,
)
_ANALYTICS_KEYWORDS = frozenset([
    "revenue", "quarter", "fiscal", "account", "accounts", "product", "growth",
    "segment", "metric", "trend", "churn", "renewal", "upsell", "downsell",
    "quantity", "usage", "breakdown", "compare", "versus", "delta", "customer",
])


def _has_analytics_signal(query: str) -> bool:
    """True if the query contains an analytics signal word, even with minor typos."""
    if _ANALYTICS_SIGNAL.search(query):
        return True
    import difflib
    tokens = re.findall(r"\b\w{5,}\b", query.lower())
    for tok in tokens:
        if difflib.get_close_matches(tok, _ANALYTICS_KEYWORDS, n=1, cutoff=0.82):
            return True
    return False


_SINGULAR_RE = re.compile(
    r"\b(?:top|bottom|biggest|largest|highest|smallest|lowest|best|worst)\s+(?:single\s+|one\s+)?"
    r"(?:account|company|customer)\b"
    r"|\bwhich\s+(?:account|company|customer)\s+(?:has|is|have)\b", re.I
)


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
    return _get_extractor().extract(_fix_typos(query))


def _find_cfy_phrases(text: str) -> list[str]:
    """Detect cfy_geo/cfy_area/cfy_region phrases typed in `text` — longest-first,
    exact (case-insensitive) match. No fuzzy pass here — the rule-based path
    handles typos; the spaCy path keeps this strict."""
    nodes = get_geo_nodes()
    found: list[str] = []
    for n in sorted(nodes, key=lambda x: len(x["value"]), reverse=True):
        val = n["value"]
        if re.search(r"\b" + re.escape(val) + r"\b", text, re.IGNORECASE):
            if val not in found:
                found.append(val)
    # Drop a value that is a proper prefix of another kept value ('EMEA' when 'EMEA South' is also found).
    return [v for v in found
            if not any(other != v and other.upper().startswith(v.upper() + " ") for other in found)]


def _scrub(d: dict, query: str, sku_canonicals: list[str], cfy_phrases: list[str]) -> dict:
    """Drop products / accounts / geos that come from inside a SKU or cfy span.

    - A SKU like 'ZDX-ADV-PROBES-GCM-1' tokenises to include 'ZDX' which otherwise
      hits product_l1 → remove that product.
    - A cfy phrase like 'EMEA South' / 'IND Gov' / 'EMEA DACH' tokenises to include
      'South' / 'Gov' / plain 'EMEA' which otherwise leak as account / geo.
    """
    def _tokens(phrase: str) -> set[str]:
        return {t.upper() for t in re.findall(r"[A-Za-z0-9]+", phrase) if t}

    sku_tokens: set[str] = set()
    for s in sku_canonicals:
        sku_tokens |= _tokens(s)
    cfy_tokens: set[str] = set()
    for c in cfy_phrases:
        cfy_tokens |= _tokens(c)

    # Scrub products that match a SKU sub-token (and are not themselves a SKU)
    d["products_raw"] = [
        p for p in d["products_raw"]
        if p.upper() not in sku_tokens or p.upper() in {s.upper() for s in sku_canonicals}
    ]

    # Scrub geo canonicals already covered more specifically by a cfy phrase.
    # 'EMEA South' cfy_area → drop plain 'EMEA' from the broad geo_raw.
    cfy_prefix_canons = {p.split()[0].upper() for p in cfy_phrases if " " in p}
    d["geo_raw"] = [g for g in d["geo_raw"] if g.upper() not in cfy_prefix_canons]

    # Scrub account if it is just a sub-token of a SKU ('PLUS' from 'ZDX-ADV-PLUS-GCM-10000')
    # or a cfy phrase ('South', 'Gov').
    if d.get("account_raw"):
        a = d["account_raw"].strip()
        if (a.upper() in sku_tokens
                or a.upper() in cfy_tokens
                or a.upper() in {s.upper() for s in sku_canonicals}
                or a.upper() in {c.upper() for c in cfy_phrases}):
            d["account_raw"] = None

    return d


def extract(query: str) -> ExtractedQuery:
    """S1 drop-in: returns the legacy ExtractedQuery shape."""
    # Normalise query/function-word typos ('teh'→'the', 'fpr'→'for', 'quaters'→'quarters')
    # BEFORE spaCy NER so stray typos never surface as capitalised entity candidates.
    text = _fix_typos(query)

    # Detect SKUs and cfy territory phrases on the typo-fixed text (same source
    # of truth as the rule-based path — core.skus + core.geo).
    sku_canonicals = [c for _, _, c in _skus.find_skus_in(text)]
    cfy_phrases    = _find_cfy_phrases(text)

    # Build token sets for scrubbing (same logic as inside _scrub)
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

    # Collect all accounts across all groups (de-duplicated), drop SKU/cfy sub-tokens
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

    # Intent was inferred before scrubbing; re-derive when account disappeared:
    # LOOKUP → AGGREGATE when no account survived; → RANK when operator is set.
    if d["intent"] == "LOOKUP" and not all_accounts:
        d["intent"] = "RANK" if d.get("operator") else "AGGREGATE"

    return ExtractedQuery(
        raw_query        = d["raw_query"],
        intent           = Intent(d["intent"]),
        account_raw      = primary_account,
        accounts_raw     = all_accounts,
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
        sku_raw          = sku_canonicals,
        geo_detail_raw   = cfy_phrases,
        missing_critical = (
            ["not_arr_query"] if not _has_analytics_signal(query) else d["missing_critical"]
        ),
    )


# Same signature as s1_extract.find_slots so S0 decomposer can swap engines.
def find_slots(query: str) -> dict:
    res = _get_extractor().extract(_fix_typos(query))
    g = res.primary
    return {
        "accounts": [a for grp in res.groups for a in grp.accounts],
        "products": g.products,
        "geo":      g.geo,
        "segments": g.segments,
        "fiscal":   g.fiscal,
    }
