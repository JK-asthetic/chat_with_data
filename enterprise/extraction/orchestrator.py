"""Extraction Orchestrator — runs all 7 deterministic tools in parallel.

Flow:
  1. spaCy NER -> ExtractedQuery (sync, fast)
  2. asyncio.gather(product, company, fiscal, geo, geo_detail, sku, segment, order_type)
  3. Merge into ResolvedEntities

Zero LLM calls. Pure deterministic Python.
"""
from __future__ import annotations

import asyncio
from typing import Any

from pipeline.models import (
    AccountFilter,
    ExtractedQuery,
    GeoFilter,
    Metric,
    ProductFilter,
    ResolvedEntities,
)
from core.log import entity
from extraction import spacy_ner
from extraction.tools import (
    product_tool,
    company_tool,
    fiscal_tool,
    geo_tool,
    sku_tool,
    segment_tool,
    order_type_tool,
)


async def _resolve_async(extracted: ExtractedQuery) -> ResolvedEntities:
    """Run all deterministic tools concurrently on ExtractedQuery."""
    # 1. Accounts
    account_task = company_tool.resolve_accounts(extracted.account_raw, extracted.accounts_raw)

    # 2. Fiscal
    fiscal_task = fiscal_tool.resolve_fiscal(
        extracted.fiscal_raw,
        raw_query=extracted.raw_query,
    )

    # 3. Geo broad
    geo_task = geo_tool.resolve_geo(extracted.geo_raw)

    # 4. Geo detail
    geo_detail_task = geo_tool.resolve_geo_detail(extracted.geo_detail_raw)

    # 5. SKU
    sku_task = sku_tool.resolve_skus(extracted.sku_raw)

    # 6. Segment
    segment_task = segment_tool.resolve_segments(extracted.segment_raw)

    # 7. Order type
    order_type_task = order_type_tool.resolve_order_types(extracted.order_type_raw)

    (
        (account_filter, company_matches, company_ambiguous),
        (fiscal_obj, fiscal_valid, fiscal_warn),
        (geo_resolved, geo_invalid_list),
        geo_detail_resolved,
        sku_resolved,
        (segment_resolved, segment_invalid_list),
        order_type_resolved,
    ) = await asyncio.gather(
        account_task,
        fiscal_task,
        geo_task,
        geo_detail_task,
        sku_task,
        segment_task,
        order_type_task,
    )

    # Products (sync in-memory hierarchy lookup)
    product_filters, product_ambiguous, candidates_map, hierarchy_cands = product_tool.resolve_products(
        extracted.products_raw
    )

    product_primary = product_filters[0] if product_filters else None
    product_cand_filters: list[ProductFilter] = []
    product_hier_filters = [
        ProductFilter.from_path(tuple(path))
        for p_list in hierarchy_cands.values() for path in p_list
    ]
    product_level = product_tool.detect_product_level(extracted.raw_query)

    # GeoFilter mapping
    geo_filter_obj = GeoFilter(col="cfy_geo", value=geo_resolved[0], values=list(geo_resolved)) if geo_resolved else None
    geo_detail_obj = geo_detail_resolved[0] if geo_detail_resolved else None

    # Ambiguities tracking
    ambiguities: list[str] = []
    if company_ambiguous:
        ambiguities.append("company")
    if product_ambiguous:
        ambiguities.append("product")
    if product_hier_filters:
        ambiguities.append("product_hierarchy")
    if not fiscal_valid:
        ambiguities.append("fiscal")
    if geo_invalid_list:
        ambiguities.append("geo")
    if segment_invalid_list:
        ambiguities.append("segment")

    return ResolvedEntities(
        extracted=extracted,
        product_filter=product_primary,
        product_filters=product_filters,
        product_level=product_level,
        product_ambiguous=product_ambiguous,
        product_candidates=product_cand_filters,
        product_hierarchy_candidates=product_hier_filters,
        account_filter=account_filter,
        company_matches=company_matches,
        company_ambiguous=company_ambiguous,
        fiscal=fiscal_obj,
        fiscal_valid=fiscal_valid,
        fiscal_warning=fiscal_warn,
        metric=Metric(name=extracted.metric_raw),
        geo_filter=geo_filter_obj,
        geo_invalid=bool(geo_invalid_list),
        geo_detail_filter=geo_detail_obj,
        segment_filter=segment_resolved[0] if segment_resolved else None,
        segment_invalid=bool(segment_invalid_list),
        order_type_filter=order_type_resolved[0] if order_type_resolved else None,
        sku_filter=sku_resolved[0] if sku_resolved else None,
        ambiguities=ambiguities,
    )


async def resolve_async(query: str) -> ResolvedEntities:
    """Asynchronous entry point: spaCy extract + all deterministic tools."""
    extracted = spacy_ner.extract(query)
    return await _resolve_async(extracted)


def resolve(query: str) -> ResolvedEntities:
    """Synchronous entry point: spaCy extract + all deterministic tools."""
    return asyncio.run(resolve_async(query))


def log_resolved(r: ResolvedEntities) -> None:
    """Print every extracted entity with its classification to the terminal."""
    ex = r.extracted

    af = r.account_filter
    if af and af.account_id:
        entity("account", f"{af.account_name}  [{'parent company' if af.level == 'parent' else 'end user'}]  id={af.account_id}  "
                          f"parent={af.parent_name or '-'}  parent_id={af.parent_id or '-'}")
        if af.multiple:
            entity("", f"also: {', '.join(af.multiple)}")
    elif ex.accounts_raw or ex.account_raw:
        entity("account", f"UNRESOLVED raw={ex.accounts_raw or ex.account_raw}"
                          f"{'  (ambiguous)' if r.company_ambiguous else ''}")
    for m in r.company_matches[:5] if not (af and af.account_id) else []:
        entity("", f"candidate: {m.account_name}  [{'parent' if m.level == 'parent' else 'end user'}]  id={m.account_id}  "
                   f"parent={m.parent_name or '-'}  parent_id={m.parent_id or '-'}  score={m.score}")

    if r.geo_filter:
        vals = r.geo_filter.values or [r.geo_filter.value]
        entity("geo", f"{r.geo_filter.col} = {', '.join(repr(v) for v in vals)}  (level: {r.geo_filter.level})")
    if r.geo_detail_filter:
        g = r.geo_detail_filter
        entity("geo", f"{g.col} = {g.value!r}  (level: {g.level})")
    if ex.geo_raw and not r.geo_filter:
        entity("geo", f"UNRESOLVED raw={ex.geo_raw}")

    for p in r.product_filters or ([r.product_filter] if r.product_filter else []):
        entity("product", f"{p.display}  (level: {p.level_label})")
    for pc in r.product_candidates + r.product_hierarchy_candidates:
        entity("", f"product candidate: {pc.display}  ({pc.level_label})")
    if r.product_level:
        entity("product", f"breakdown by product_l{r.product_level}  (all L{r.product_level} products)")

    if r.fiscal and (r.fiscal.fiscal_quarter_label or r.fiscal.fiscal_year_label or r.fiscal.quarter_labels):
        f = r.fiscal
        entity("fiscal", (f.fiscal_quarter_label or f.fiscal_year_label or ", ".join(f.quarter_labels))
               + (f"  (month: {f.month_start[:7]})" if f.month_start else ""))
    if r.segment_filter:
        entity("segment", str(r.segment_filter))
    if r.order_type_filter:
        entity("order_type", str(r.order_type_filter))
    if r.sku_filter:
        entity("sku", str(r.sku_filter))
    entity("metric", f"{r.metric.name}  intent={ex.intent}  limit={ex.limit_n}")
