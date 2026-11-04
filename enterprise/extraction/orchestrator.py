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
    product_cand_filters = [ProductFilter(l1=c, deepest_level=1) for c_list in candidates_map.values() for c in c_list]
    product_hier_filters = [
        ProductFilter(l1=path[0], l2=path[1] if len(path) > 1 else None, deepest_level=len(path))
        for p_list in hierarchy_cands.values() for path in p_list
    ]

    # GeoFilter mapping
    geo_filter_obj = GeoFilter(col="cfy_geo", value=geo_resolved[0]) if geo_resolved else None
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
