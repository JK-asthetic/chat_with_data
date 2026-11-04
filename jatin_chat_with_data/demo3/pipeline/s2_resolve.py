"""
Stage 2 — Six parallel validation/enrichment tools.

Each tool takes one raw field from ExtractedQuery and returns the
enriched, validated, DB-canonical version.  All 6 run concurrently
via asyncio.gather.

Tool 1 — Product Validator    → product_filter: list[ProductFilter]
Tool 2 — Account Resolver     → account_filter: AccountFilter
Tool 3 — Fiscal Normalizer    → fiscal: Fiscal  (validates vs DB)
Tool 4 — Metric Resolver      → metric: Metric
Tool 5 — Geo Validator        → geo_filter: list[str]
Tool 6 — Segment Validator    → segment_filter: list[str]
"""
from __future__ import annotations

import asyncio
import difflib
import re

from rapidfuzz import fuzz as _rfuzz
from datetime import date
from typing import Optional

from core import hierarchy
from core.config import get_schema, get_settings
from core.db import check_pg_trgm, query_all, query_one
from core.fiscal import quarter_of, trailing_quarters
from pipeline.models import (
    AccountFilter,
    CompanyMatch,
    ExtractedQuery,
    Fiscal,
    Intent,
    Metric,
    ProductFilter,
    ResolvedEntities,
)

_schema   = get_schema
_settings = get_settings

# ══════════════════════════════════════════════════════════════════════════════
# Tool 1 — Product Validator
# ══════════════════════════════════════════════════════════════════════════════

def _drop_ancestors(filters: list[ProductFilter]) -> list[ProductFilter]:
    """'ZIA SWG ARR' names a product and its own sub-product: the narrower one wins."""
    paths = [f.path for f in filters]
    return [f for f, p in zip(filters, paths)
            if not any(len(q) > len(p) and q[:len(p)] == p for q in paths)]


def _validate_products(
    products_raw: list[str],
) -> tuple[list[ProductFilter], bool, dict[str, list[str]], dict[str, list[list[str]]]]:
    """
    Maps raw product phrases → ProductFilter objects at whatever hierarchy level they name.
    Returns: (resolved, ambiguous, candidates_map, hierarchy_candidates)
    hierarchy_candidates: phrase → every hierarchy path it could mean (resolved by S3).
    """
    aliases = get_schema().get("product_aliases", {})

    resolved:             list[ProductFilter]       = []
    ambiguous             = False
    candidates:           dict[str, list[str]]      = {}
    hierarchy_candidates: dict[str, list[list[str]]] = {}

    for raw in products_raw:
        key = raw.upper().strip()

        # What the user typed wins; an alias is only used when it is not itself a hierarchy name.
        paths = hierarchy.find(raw) or hierarchy.find(aliases.get(key, ""))
        if len(paths) == 1:
            resolved.append(ProductFilter.from_path(paths[0]))
            continue
        if paths:
            hierarchy_candidates[raw] = [list(p) for p in paths]
            continue

        # Alias whose target is not in the hierarchy (stale alias): keep it as an l1 filter.
        if key in aliases:
            resolved.append(ProductFilter(l1=aliases[key], deepest_level=1))
            continue

        # Partial match → l1 name ambiguity
        partials = list(dict.fromkeys(
            val for alias, val in aliases.items()
            if key in alias or alias in key
        ))

        if len(partials) == 1:
            resolved.append(ProductFilter(l1=partials[0], deepest_level=1))
        elif partials:
            candidates[raw] = partials
            ambiguous = True
        # else: completely unknown — skip

    return _drop_ancestors(resolved), ambiguous, candidates, hierarchy_candidates


# ══════════════════════════════════════════════════════════════════════════════
# Tool 2 — Account Resolver
# ══════════════════════════════════════════════════════════════════════════════

_HAS_TRGM: Optional[bool] = None

def _trgm_available() -> bool:
    global _HAS_TRGM
    if _HAS_TRGM is None:
        _HAS_TRGM = check_pg_trgm()
    return _HAS_TRGM


def _best_word_ratio(cand: str, name: str) -> float:
    """Max per-word similarity of cand vs any single word of name.

    Uses rapidfuzz WRatio (handles transpositions, insertions, deletions better than
    difflib). 'seimnes' vs 'Siemens AG' → max(WRatio('seimnes','siemens')/100, ...) ≈ 0.90.
    """
    words = [w for w in name.lower().split() if w]
    if not words:
        return 0.0
    c = cand.lower()
    return max(_rfuzz.WRatio(c, w) / 100.0 for w in words)


def _adjacent_swaps(c: str) -> list[str]:
    out = [c]
    for i in range(len(c) - 1):
        if c[i] != c[i + 1]:
            out.append(c[:i] + c[i + 1] + c[i] + c[i + 2:])
    return out


def _search_company_trgm(raw: str) -> list[CompanyMatch]:
    """Shortlist via two cheap index-friendly probes against t6_arr_contract (active customers only).

    Searching t6_arr_contract.account_name restricts matches to companies Zscaler actually
    transacts with. account_id is available in the same table — no join to dim_account needed.
    """
    q = raw.lower()
    q4 = q[:4]
    prefix_variants = list({
        f"{q4[i]}{q4[j]}%"
        for i in range(len(q4))
        for j in range(i + 1, len(q4))
    })
    rows = query_all(
        """
        (
          SELECT DISTINCT account_id::text AS account_id, account_name
          FROM t6_arr_contract
          WHERE is_latest = true
            AND lower(account_name) %% %(q)s
          LIMIT 50
        )
        UNION
        (
          SELECT DISTINCT account_id::text AS account_id, account_name
          FROM t6_arr_contract
          WHERE is_latest = true
            AND lower(account_name) LIKE ANY(%(prefixes)s::text[])
          LIMIT 200
        )
        """,
        {"q": q, "prefixes": prefix_variants},
    )
    matches: list[CompanyMatch] = []
    for r in rows:
        name = r["account_name"]
        score = 1.0 if q == name.lower() else _best_word_ratio(raw, name)
        matches.append(CompanyMatch(account_id=r["account_id"],
                                    account_name=name,
                                    score=score))
    matches.sort(key=lambda x: x.score, reverse=True)
    return matches[:8]


def _search_company_ilike(raw: str) -> list[CompanyMatch]:
    """Fallback when pg_trgm isn't installed. Searches t6_arr_contract accounts only."""
    short = len(raw) <= 4
    pattern = f"{raw}%" if short else f"%{raw}%"
    rows = query_all(
        """
        SELECT account_id, account_name FROM (
            SELECT DISTINCT account_id::text AS account_id, account_name,
              CASE
                WHEN LOWER(account_name) = LOWER(%(q)s)             THEN 0
                WHEN LOWER(account_name) LIKE LOWER(%(q)s) || ' %%' THEN 1
                ELSE 2
              END AS sort_key
            FROM t6_arr_contract
            WHERE is_latest = true
              AND account_name ILIKE %(p)s
        ) sub
        ORDER BY sort_key, LENGTH(account_name)
        LIMIT 20
        """,
        {"p": pattern, "q": raw},
    )
    matches = []
    for r in rows:
        name = r["account_name"]
        base   = difflib.SequenceMatcher(None, raw.lower(), name.lower()).ratio()
        weight = min(len(raw), len(name)) / max(len(raw), len(name))
        score  = base * (0.5 + 0.5 * weight)
        if raw.lower() == name.lower():
            score = 1.0
        matches.append(CompanyMatch(account_id=r["account_id"],
                                    account_name=name,
                                    score=score))
    matches.sort(key=lambda x: x.score, reverse=True)
    return matches[:8]


_COMPANY_SCORE_FLOOR = 0.70   # drop matches below this — "wha", "the", etc. have no real neighbour above this


async def _resolve_one_account(raw: str) -> list[CompanyMatch]:
    """Resolve a single account name → up to 1 best CompanyMatch (or empty list)."""
    fn = _search_company_trgm if _trgm_available() else _search_company_ilike
    matches = await asyncio.to_thread(fn, raw)
    matches = [m for m in matches if m.score >= _COMPANY_SCORE_FLOOR]
    if not matches:
        return []
    cfg = get_settings()
    top = matches[0].score
    multi_high = sum(1 for m in matches if m.score >= 0.75)
    # Ambiguous single-account → return all candidates (caller decides)
    if top < cfg.COMPANY_SCORE_THRESHOLD or multi_high > 1:
        return matches  # marked ambiguous by caller
    return matches[:1]


async def _tool_account(
    raw: Optional[str],
    all_raws: Optional[list[str]] = None,
) -> tuple[list[CompanyMatch], bool]:
    """Returns (matches, is_ambiguous).

    When `all_raws` has more than one entry (multi-account query), resolve each
    name independently and take the best single match per name — the result is
    a list of resolved companies with no ambiguity flag (multi-account is valid).

    Single-account path: ambiguous when top score is below threshold or multiple
    names score ≥ 0.75.
    """
    names = all_raws if all_raws else ([raw] if raw else [])
    if not names:
        return [], False

    fn = _search_company_trgm if _trgm_available() else _search_company_ilike

    if len(names) == 1:
        # Original single-account path with ambiguity detection
        matches = await asyncio.to_thread(fn, names[0])
        matches = [m for m in matches if m.score >= _COMPANY_SCORE_FLOOR]
        if not matches:
            return [], False
        cfg = get_settings()
        top = matches[0].score
        multi_high = sum(1 for m in matches if m.score >= 0.75)
        ambiguous = top < cfg.COMPANY_SCORE_THRESHOLD or multi_high > 1
        return matches, ambiguous

    # Multi-account: resolve each in parallel, take best match per name
    tasks = [_resolve_one_account(n) for n in names]
    per_name = await asyncio.gather(*tasks)
    resolved: list[CompanyMatch] = []
    seen_ids: set[str] = set()
    needs_confirm = False
    for raw_name, candidates in zip(names, per_name):
        if not candidates:
            continue
        best = candidates[0]
        if best.account_id not in seen_ids:
            # Attach the raw typed name so S3 can show "you typed X → we found Y"
            best = best.model_copy(update={"matched_raw": raw_name})
            resolved.append(best)
            seen_ids.add(best.account_id)
        # Flag for confirmation if resolved name looks very different from what was typed
        from rapidfuzz import fuzz as _rfuzz
        similarity = _rfuzz.WRatio(raw_name.lower(), best.account_name.lower()) / 100.0
        if similarity < 0.70:
            needs_confirm = True
    return resolved, needs_confirm


# ══════════════════════════════════════════════════════════════════════════════
# Tool 3 — Fiscal Normalizer
# ══════════════════════════════════════════════════════════════════════════════

_Q_FIRST_RE = re.compile(r"Q([1-4])\s*(?:FY\s*|fiscal\s*)?(\d{2,4})", re.IGNORECASE)
_FY_RE      = re.compile(r"(?:FY\s*|fiscal\s+year\s*)?(\d{2,4})(?:[\s\-\/]?Q([1-4]))?", re.IGNORECASE)


def _parse_fiscal_raw(fiscal_raw: Optional[str]) -> Fiscal:
    """Parse raw fiscal string → Fiscal model (DB labels, no DB validation).

    Handles:
    - Single quarter: 'Q1FY26' → fiscal_quarter_label='FY 2026 Q1'
    - Multiple quarters: 'Q1FY26 vs Q3FY26' → quarter_labels=['FY 2026 Q1','FY 2026 Q3'], is_range=True
    - Fiscal year only: 'FY26' → fiscal_year_label='FY 2026'
    """
    if not fiscal_raw:
        return Fiscal()

    def _full(yr: str) -> str:
        return f"20{yr}" if len(yr) == 2 else yr

    # Check for multiple named quarters joined by 'vs', 'and', ',', 'to', 'through', etc.
    all_q = [(int(m.group(1)), _full(m.group(2))) for m in _Q_FIRST_RE.finditer(fiscal_raw)]
    distinct_q = list(dict.fromkeys(all_q))
    if len(distinct_q) >= 2:
        labels = [f"FY {yr} Q{q}" for q, yr in distinct_q]
        return Fiscal(quarter_labels=labels, is_range=True)

    if len(distinct_q) == 1:
        q, yr = distinct_q[0]
        fy_label = f"FY {yr}"
        fq_label = f"{fy_label} Q{q}"
        return Fiscal(fy=int(yr), quarter=q, is_range=False,
                      fiscal_quarter_label=fq_label, fiscal_year_label=fy_label)

    m = _FY_RE.search(fiscal_raw)
    if m:
        yr = _full(m.group(1))
        q  = int(m.group(2)) if m.group(2) else None
        fy_label = f"FY {yr}"
        fq_label = f"{fy_label} Q{q}" if q else None
        return Fiscal(fy=int(yr), quarter=q, is_range=False,
                      fiscal_quarter_label=fq_label, fiscal_year_label=fy_label)

    return Fiscal()


_REL_N_RE = re.compile(r"\b(?:last|past|previous|prior)\s+(\d{1,2})\s+(quarters?|(?:fiscal\s+)?years?)\b", re.IGNORECASE)
_REL_Q_RE = re.compile(r"\b(?:last|previous|prior)\s+quarter\b", re.IGNORECASE)
_CUR_Q_RE = re.compile(r"\b(?:this|current)\s+quarter\b", re.IGNORECASE)
_YTD_RE   = re.compile(r"\bytd\b|\byear[- ]to[- ]date\b", re.IGNORECASE)
_REL_Y_RE = re.compile(r"\b(?:last|previous|prior)\s+(?:fiscal\s+)?year\b|\blast\s+fy\b", re.IGNORECASE)
_CUR_Y_RE = re.compile(r"\b(?:this|current)\s+(?:fiscal\s+)?year\b|\bcurrent\s+fy\b", re.IGNORECASE)


def _quarter(label: str) -> Fiscal:
    parts = label.split()  # 'FY 2027 Q1'
    return Fiscal(fy=int(parts[1]), quarter=int(parts[2][1]), fiscal_quarter_label=label,
                  fiscal_year_label=f"FY {parts[1]}")


def _parse_relative(text: str, today: Optional[date] = None) -> Optional[Fiscal]:
    """Resolve 'last quarter', 'this quarter', 'last 6 quarters', 'last/this year' and YTD
    against today's fiscal quarter. 'Last N quarters' ends at the current quarter, inclusive."""
    if not text:
        return None
    cur_fy, cur_fq = quarter_of(today or date.today())
    if m := _REL_N_RE.search(text):
        n = int(m.group(1)) * (4 if m.group(2).lower().endswith(("year", "years")) else 1)   # 'last 3 years' = 12 quarters
        labels = trailing_quarters(cur_fq, max(1, min(n, 20)))
        return Fiscal(quarter_labels=labels, is_range=len(labels) > 1)
    if _REL_Q_RE.search(text):
        return _quarter(trailing_quarters(cur_fq, 2)[0])
    if _CUR_Q_RE.search(text):
        return _quarter(cur_fq)
    if _YTD_RE.search(text):
        labels = [q for q in trailing_quarters(cur_fq, 4) if q.startswith(cur_fy)]
        return Fiscal(quarter_labels=labels, is_range=len(labels) > 1)
    if _REL_Y_RE.search(text):
        year = int(cur_fy.split()[1]) - 1
        return Fiscal(fy=year, fiscal_year_label=f"FY {year}")
    if _CUR_Y_RE.search(text):
        return Fiscal(fy=int(cur_fy.split()[1]), fiscal_year_label=cur_fy)
    return None


async def _tool_fiscal(fiscal_raw: Optional[str], fy_label: Optional[str], fq_label: Optional[str],
                       raw_query: str = "") -> tuple[Fiscal, bool, Optional[str]]:
    """Parse + validate fiscal period. Returns (fiscal, valid, warning)."""
    # An explicit period typed by the user wins; otherwise relative words resolve against today.
    relative = None if (fy_label or fq_label) else _parse_relative(fiscal_raw or raw_query)
    if relative and relative.quarter_labels:
        return relative, True, None  # ranges are not DB-validated
    fiscal = relative or _parse_fiscal_raw(fiscal_raw)

    # Prefer S1 regex labels (more reliable) over Tool 3 parse when available
    if fy_label:
        fiscal = fiscal.model_copy(update={"fiscal_year_label": fy_label})
    if fq_label:
        fiscal = fiscal.model_copy(update={"fiscal_quarter_label": fq_label})

    if not fiscal.fiscal_year_label and not fiscal.fiscal_quarter_label:
        return fiscal, True, None  # no fiscal — not an error

    def _check() -> tuple[bool, Optional[str]]:
        if fiscal.fiscal_quarter_label:
            row = query_one(
                "SELECT 1 FROM data_arr WHERE fiscal_quarter = %(fq)s LIMIT 1",
                {"fq": fiscal.fiscal_quarter_label},
            )
            if not row:
                return False, f"No data for fiscal_quarter='{fiscal.fiscal_quarter_label}'"
        elif fiscal.fiscal_year_label:
            row = query_one(
                "SELECT 1 FROM data_arr WHERE fiscal_year = %(fy)s LIMIT 1",
                {"fy": fiscal.fiscal_year_label},
            )
            if not row:
                return False, f"No data for fiscal_year='{fiscal.fiscal_year_label}'"
        return True, None

    valid, warning = await asyncio.to_thread(_check)
    return fiscal, valid, warning


TREND_DEFAULT_QUARTERS = 6
_LAST_N_RE = re.compile(r"\b(?:last|past)\s+(\d{1,2})\s+quarters?\b", re.IGNORECASE)


def _trend_window(extracted: ExtractedQuery, fiscal: Fiscal, today: Optional[date] = None) -> Optional[Fiscal]:
    """A trend needs several periods: no period → trailing quarters ending now,
    one named quarter → trailing quarters ending there. A fiscal year or range is left alone."""
    if extracted.intent != Intent.TREND or fiscal.quarter_labels:
        return None
    if fiscal.fiscal_year_label and not fiscal.fiscal_quarter_label:
        return None  # a whole fiscal year is already several quarters
    m = _LAST_N_RE.search(f"{extracted.fiscal_raw or ''} {extracted.raw_query}")
    n = max(2, min(int(m.group(1)), 20)) if m else TREND_DEFAULT_QUARTERS
    end = fiscal.fiscal_quarter_label or quarter_of(today or date.today())[1]
    return Fiscal(quarter_labels=trailing_quarters(end, n), is_range=True)


# ══════════════════════════════════════════════════════════════════════════════
# Tool 4 — Metric Resolver
# ══════════════════════════════════════════════════════════════════════════════

async def _tool_metric(metric_raw: str) -> Metric:
    """Map raw metric name → Metric (table, col, variant) from schema."""
    metrics = get_schema().get("metrics", {})
    key = metric_raw.upper().strip().replace(" ", "_")
    defn = metrics.get(key)
    if defn:
        return Metric(
            name    = key,
            table   = defn["table"],
            col     = defn["col"],
            variant = defn.get("variant", "snapshot"),
        )
    # Default: ARR on data_arr
    return Metric(name="ARR", table="data_arr", col="arr", variant="snapshot")


# ══════════════════════════════════════════════════════════════════════════════
# Tool 5 — Geo Validator
# ══════════════════════════════════════════════════════════════════════════════

async def _tool_geo(geo_raw: list[str]) -> tuple[list[str], list[str]]:
    """
    Maps each raw geo string → actual t6_arr_contract geo column values (AMS ECE, AMS MPH, APJ, EMEA).
    "Americas" / "AMS" expands to [AMS ECE, AMS MPH].
    Returns (resolved_list, invalid_list).
    """
    schema   = get_schema()
    aliases  = schema.get("geo_aliases", {})
    expand   = schema.get("geo_expand", {})   # canonical label → list[str] of actual geo column values
    resolved: list[str] = []
    invalid:  list[str] = []

    def _add_expanded(canon: str) -> None:
        for v in expand.get(canon, [canon]):
            if v not in resolved:
                resolved.append(v)

    for raw in geo_raw:
        key = raw.upper().strip()
        canon = aliases.get(key)
        if canon:
            _add_expanded(canon)
            continue
        # Partial match against alias keys
        partials = list(dict.fromkeys(
            v for k, v in aliases.items()
            if key in k or k in key
        ))
        if partials:
            for p in partials:
                _add_expanded(p)
        else:
            invalid.append(raw)

    return resolved, invalid


async def _tool_geo_detail(geo_detail_raw: list[str]) -> "list[GeoFilter]":
    """
    Tool 5b — resolves detailed cfy territory phrases to (col, value) pairs.
    Maps to t6_arr_contract columns: cfy_geo→geo, cfy_area→area, cfy_region→region.

    Simple geo canonicals (Americas/APJ/EMEA) are handled by _tool_geo and skipped here.
    """
    from core.geo import search_geo
    from pipeline.models import GeoFilter

    # These are handled by the simple geo tool (_tool_geo → end_user_parent_geo)
    _SIMPLE_CANONICALS = {"Americas", "APJ", "EMEA"}

    resolved: list[GeoFilter] = []
    seen_values: set[str] = set()

    for phrase in geo_detail_raw:
        node = search_geo(phrase)
        if not node:
            continue
        if node["value"] in _SIMPLE_CANONICALS:
            continue  # let _tool_geo handle it via end_user_parent_geo
        if node["value"] not in seen_values:
            seen_values.add(node["value"])
            resolved.append(GeoFilter(col=node["col"], value=node["value"]))

    return resolved


# ══════════════════════════════════════════════════════════════════════════════
# Tool 6 — Segment Validator
# ══════════════════════════════════════════════════════════════════════════════

async def _tool_segment(segment_raw: list[str]) -> tuple[list[str], list[str]]:
    """
    Maps raw segment strings → canonical DB values (market_segment column).
    Returns (resolved_list, invalid_list).
    """
    aliases = get_schema().get("segment_aliases", {})
    resolved: list[str] = []
    invalid:  list[str] = []

    for raw in segment_raw:
        key = raw.upper().strip()
        canon = aliases.get(key)
        if canon:
            if canon not in resolved:
                resolved.append(canon)
        else:
            # Keep original casing if not found — may still be a valid DB value
            invalid.append(raw)

    return resolved, invalid


# ══════════════════════════════════════════════════════════════════════════════
# Tool 7 — SKU Resolver
# ══════════════════════════════════════════════════════════════════════════════

_SKU_SCORE_FLOOR = 0.78   # per-char similarity floor for a fuzzy SKU match


def _search_sku_trgm(raw: str) -> list[str]:
    """Return up to 10 sku values from t6_arr_contract that fuzzy-match raw (pg_trgm probe)."""
    q = raw.lower()
    q4 = q[:4]
    prefix_variants = list({
        f"{q4[i]}{q4[j]}%"
        for i in range(len(q4))
        for j in range(i + 1, len(q4))
    })
    rows = query_all(
        """
        (
          SELECT DISTINCT sku FROM t6_arr_contract
          WHERE is_latest = true AND lower(sku) %% %(q)s
          LIMIT 30
        )
        UNION
        (
          SELECT DISTINCT sku FROM t6_arr_contract
          WHERE is_latest = true AND lower(sku) LIKE ANY(%(prefixes)s::text[])
          LIMIT 100
        )
        """,
        {"q": q, "prefixes": prefix_variants},
    )
    return [r["sku"] for r in rows if r["sku"]]


def _search_sku_ilike(raw: str) -> list[str]:
    """Fallback SKU search without pg_trgm."""
    short = len(raw) <= 4
    pattern = f"{raw}%" if short else f"%{raw}%"
    rows = query_all(
        "SELECT DISTINCT sku FROM t6_arr_contract WHERE is_latest = true AND sku ILIKE %(p)s LIMIT 100",
        {"p": pattern},
    )
    return [r["sku"] for r in rows if r["sku"]]


async def _tool_sku(sku_raw: list[str]) -> list[str]:
    """Resolve raw SKU tokens → canonical sku values from t6_arr_contract.

    S1 already resolved any typed SKU to the canonical form via a 100% exact
    match against the fixed t6_arr_contract.sku vocabulary (see core/skus.py).
    This tool just dedupes + canonicalises in case a caller passes a lower-cased
    variant directly. No fuzzy / similarity search — SKUs are a fixed list.
    """
    if not sku_raw:
        return []
    from core import skus as _skus
    resolved: list[str] = []
    for raw in sku_raw:
        if not raw or not raw.strip():
            continue
        canon = _skus.canonical(raw) or raw.strip()
        if canon not in resolved:
            resolved.append(canon)
    return resolved


# ══════════════════════════════════════════════════════════════════════════════
# Orchestrator — run all 6 tools concurrently
# ══════════════════════════════════════════════════════════════════════════════

async def _resolve_async(extracted: ExtractedQuery) -> ResolvedEntities:
    # Run tools concurrently (Tool 7 = SKU, Tool 8 = detailed geo)
    all_raws = getattr(extracted, "accounts_raw", None) or []
    (
        (company_matches, company_ambiguous),
        (fiscal, fiscal_valid, fiscal_warn),
        metric,
        (geo_resolved, geo_invalid),
        (seg_resolved, seg_invalid),
        sku_resolved,
        geo_detail_resolved,
    ) = await asyncio.gather(
        _tool_account(extracted.account_raw, all_raws if len(all_raws) > 1 else None),
        _tool_fiscal(extracted.fiscal_raw, extracted.fiscal_year, extracted.fiscal_quarter, extracted.raw_query),
        _tool_metric(extracted.metric_raw),
        _tool_geo(extracted.geo_raw),
        _tool_segment(extracted.segment_raw),
        _tool_sku(extracted.sku_raw),
        _tool_geo_detail(extracted.geo_detail_raw),
    )

    if fiscal_valid and (trend := _trend_window(extracted, fiscal)):
        fiscal, fiscal_valid, fiscal_warn = trend, True, None

    # Tool 1 is sync (in-memory hierarchy lookup — loaded once per process)
    product_filter, product_ambiguous, product_candidates, product_hierarchy_candidates = _validate_products(
        extracted.products_raw
    )

    # Build AccountFilter from company matches
    account_filter = AccountFilter(account_raw=extracted.account_raw)
    is_multi = len(getattr(extracted, "accounts_raw", None) or []) > 1
    if company_matches and not company_ambiguous:
        if is_multi and len(company_matches) > 1:
            # Multi-account: store all resolved IDs; primary = first
            account_filter = AccountFilter(
                account_raw  = extracted.account_raw,
                account_id   = company_matches[0].account_id,
                account_name = company_matches[0].account_name,
                multiple     = [m.account_name for m in company_matches],
                account_ids  = [m.account_id for m in company_matches],
            )
        else:
            best = company_matches[0]
            account_filter = AccountFilter(
                account_raw  = extracted.account_raw,
                account_id   = best.account_id,
                account_name = best.account_name,
            )

    # Collect ambiguities for S3
    ambiguities: list[str] = []
    if product_ambiguous:
        ambiguities.append("product")
    if product_hierarchy_candidates:
        ambiguities.append("product_hierarchy")
    if company_ambiguous:
        ambiguities.append("company")
    if geo_invalid:
        ambiguities.append("geo")
    # Missing fiscal (never mentioned) OR present but not in DB
    if not fiscal.fiscal_quarter_label and not fiscal.fiscal_year_label and not fiscal.quarter_labels:
        ambiguities.append("fiscal")
    elif not fiscal_valid:
        ambiguities.append("fiscal")

    return ResolvedEntities(
        extracted                    = extracted,
        product_filter               = product_filter,
        product_ambiguous            = product_ambiguous,
        product_candidates           = product_candidates,
        product_hierarchy_candidates = product_hierarchy_candidates,
        account_filter     = account_filter,
        company_matches    = company_matches,
        company_ambiguous  = company_ambiguous,
        fiscal             = fiscal,
        fiscal_valid       = fiscal_valid,
        fiscal_warning     = fiscal_warn,
        metric             = metric,
        geo_filter         = geo_resolved,
        geo_invalid        = geo_invalid,
        geo_detail_filter  = geo_detail_resolved,
        segment_filter     = seg_resolved,
        segment_invalid    = seg_invalid,
        order_type_filter  = list(dict.fromkeys(extracted.order_type_raw)),
        sku_filter         = sku_resolved,
        ambiguities        = ambiguities,
    )


def resolve(extracted: ExtractedQuery) -> ResolvedEntities:
    """Sync entry point — runs all 6 tools in a fresh event loop."""
    return asyncio.run(_resolve_async(extracted))
