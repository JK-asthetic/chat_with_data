"""Pipeline Orchestrator — coordinates all stages in the enterprise pipeline.

Flow:
  1. Deterministic Extraction (7 tools in parallel, zero LLM calls)
  2. LLM Classification (Haiku: metric routing, intent, follow-up, strategic detection)
  3. Ambiguity & Clarification gate (max 1 card, 3 questions)
  4. Parallel Metric Agent Execution (Sonnet LLM per metric, asyncio.gather fan-out)
  5. Response Assembly & Session Memory update
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import time
from typing import Any, Optional

from pipeline.models import (
    ClassifiedQuery,
    MetricAgentRequest,
    MetricAgentResponse,
    PipelineResponse,
    ResolvedEntities,
    SubQuery,
)
from pipeline.memory import SessionMemory, Turn
from pipeline.classifier import classify
from pipeline.clarifier import clarify
from extraction.orchestrator import resolve, resolve_async
from core.mdl_registry import get_registry
from core.settings import get_ai
from core.log import step, ok, warn
from response.insight import _stream

logger = logging.getLogger(__name__)

# Dynamically loaded Agent class registry
_AGENT_REGISTRY: dict[str, type] = {}


def _load_agent_class(dot_path: str) -> type:
    module_path, class_name = dot_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def init_agent_registry() -> dict[str, type]:
    global _AGENT_REGISTRY
    if _AGENT_REGISTRY:
        return _AGENT_REGISTRY

    registry = get_registry()
    for metric_name, mdef in registry.items():
        try:
            cls = _load_agent_class(mdef.agent_class_path)
            _AGENT_REGISTRY[metric_name] = cls
        except Exception as e:
            logger.warning(f"Could not load agent for {metric_name} ({mdef.agent_class_path}): {e}")

    return _AGENT_REGISTRY


async def _run_agents_parallel(
    sub_queries: list[SubQuery],
    resolved: ResolvedEntities,
) -> list[MetricAgentResponse]:
    """Fan out to metric agents concurrently via asyncio.gather."""
    agents_map = init_agent_registry()
    tasks = []

    for sq in sub_queries:
        agent_cls = agents_map.get(sq.metric)
        if not agent_cls:
            logger.warning(f"No agent registered for metric '{sq.metric}'")
            continue

        agent = agent_cls(sq.metric)
        req = MetricAgentRequest(
            metric_name=sq.metric,
            resolved=resolved,
            question=sq.question,
        )
        tasks.append(agent.run(req))

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    valid_responses: list[MetricAgentResponse] = []
    for r in results:
        if isinstance(r, MetricAgentResponse):
            valid_responses.append(r)
        else:
            logger.error(f"Metric agent execution raised an exception: {r}")

    return valid_responses


async def run_async(
    query: str,
    memory: Optional[SessionMemory] = None,
    interactive: bool = True,
) -> PipelineResponse:
    """Main async pipeline entry point."""
    t0 = time.perf_counter()
    mem = memory if memory is not None else SessionMemory()

    # Stage 1: Deterministic extraction
    step("Stage 1 · Extraction", "running spaCy NER + 7 tools in parallel…")
    resolved = await resolve_async(query)
    ext = resolved.extracted
    entity_parts = []
    if resolved.account_filter and resolved.account_filter.account_name:
        entity_parts.append(f"account={resolved.account_filter.account_name!r}")
    if resolved.fiscal:
        entity_parts.append(f"fiscal={resolved.fiscal.fiscal_quarter_label or resolved.fiscal.fiscal_year_label or ''}")
    if resolved.geo_filter:
        entity_parts.append(f"geo={resolved.geo_filter.value!r}")
    if resolved.product_filter:
        entity_parts.append(f"product={resolved.product_filter.path}")
    if resolved.segment_filter:
        entity_parts.append(f"segment={resolved.segment_filter!r}")
    ok("Extraction done", ", ".join(entity_parts) if entity_parts else "no entities resolved")
    if resolved.ambiguities:
        warn("Ambiguities", ", ".join(resolved.ambiguities))

    # Stage 2: LLM pre-classify (metric routing + intent + follow-up)
    step("Stage 2 · Classification", f"routing query via LLM ({get_ai().models.classifier})…")
    classified: ClassifiedQuery = classify(query, resolved, mem)
    ok("Classification done",
       f"metrics={classified.metrics_needed}  intent={classified.intent}  "
       f"followup={classified.is_followup}  strategic={classified.is_strategic}")

    # Strategic question bypass
    if classified.is_strategic:
        system = (
            "You are an executive enterprise sales and finance advisor. "
            "Answer the strategic question concisely with 4-5 actionable bullet points. "
            "Cite relevant data metrics (ARR, ACV, Churn, Quotas) to measure success."
        )
        answer = _stream(system, f"Question: {query}", prefix="💡 Strategy Advisor: ", max_tokens=400)
        return PipelineResponse(
            question=query,
            agent_responses=[],
            merged_insight=answer,
            total_elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        )

    # Stage 3: Clarification check if ambiguities exist
    if (resolved.ambiguities or classified.ambiguities) and interactive:
        step("Stage 3 · Clarification", f"ambiguities: {resolved.ambiguities or classified.ambiguities}")
        clarification_res = clarify(resolved, classified)
        if not clarification_res.answerable or clarification_res.cancelled:
            return PipelineResponse(
                question=query,
                agent_responses=[],
                merged_insight=clarification_res.not_answerable_reason or "Clarification cancelled.",
                total_elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )
        if clarification_res.pinned_company and resolved.account_filter:
            resolved.account_filter.account_name = clarification_res.pinned_company.account_name
            resolved.account_filter.account_id = clarification_res.pinned_company.account_id

    # Stage 4: Parallel agent execution
    step("Stage 4 · Agent execution", f"launching {len(classified.sub_queries or classified.metrics_needed)} agent(s) in parallel…")
    sub_queries = classified.sub_queries
    if not sub_queries:
        sub_queries = [
            SubQuery(metric=m, question=classified.resolved_question or query, id=f"q{i+1}")
            for i, m in enumerate(classified.metrics_needed)
        ]

    agent_responses = await _run_agents_parallel(sub_queries, resolved)

    # Stage 5: Response assembly & memory update
    elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
    ok("Stage 5 · Done", f"total={elapsed}ms  agents_ok={len(agent_responses)}")
    response = PipelineResponse(
        question=query,
        agent_responses=agent_responses,
        total_elapsed_ms=elapsed,
    )

    # Save turns to memory for follow-up resolution
    for ar in agent_responses:
        if ar.result.success:
            mem.add(Turn(
                query=query,
                standalone=classified.resolved_question or query,
                entities={"metric": ar.metric_name},
                columns=ar.result.columns,
                rows=ar.result.rows,
            ))

    return response


def run(
    query: str,
    memory: Optional[SessionMemory] = None,
    interactive: bool = True,
) -> PipelineResponse:
    """Sync wrapper around run_async."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(run_async(query, memory, interactive))
    else:
        return asyncio.run(run_async(query, memory, interactive))
