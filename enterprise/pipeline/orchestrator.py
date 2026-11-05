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
from extraction.orchestrator import resolve, resolve_async, log_resolved
from core.mdl_registry import get_registry
from core.settings import get_ai
from core.log import step, ok, warn, entity
from response.insight import _stream

logger = logging.getLogger(__name__)

# Dynamically loaded Agent class registry
_AGENT_REGISTRY: dict[str, type] = {}
_LOOP: Optional[asyncio.AbstractEventLoop] = None


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
    ok("Extraction done")
    log_resolved(resolved)
    if resolved.ambiguities:
        warn("Ambiguities", "; ".join(resolved.ambiguities))

    # Stage 2: LLM pre-classify (metric routing + intent + follow-up)
    step("Stage 2 · Classification", f"routing query via LLM ({get_ai().models.classifier})…")
    classified: ClassifiedQuery = classify(query, resolved, mem)

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

    # Stage 3: Clarification — ask the user, then fold every answer back into the query
    effective_query = query
    pending = resolved.ambiguities or classified.ambiguities or classified.clarifications
    if pending and not interactive and classified.clarifications:
        warn("Stage 3 · Clarification skipped (non-interactive)",
             " | ".join(c.question for c in classified.clarifications))
    if pending and interactive:
        step("Stage 3 · Clarification", f"needs input: {resolved.ambiguities or classified.ambiguities or [c.question for c in classified.clarifications]}")
        res = clarify(resolved, classified)
        if not res.answerable or res.cancelled:
            return PipelineResponse(
                question=query,
                agent_responses=[],
                merged_insight=res.not_answerable_reason or "Clarification cancelled.",
                total_elapsed_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            )

        extra = " ".join([res.addendum.strip()] + [a for _, a in res.answers if a]).strip()
        if extra:
            effective_query = f"{query} ({extra})"
            step("Stage 3 · Updated question", effective_query)
            resolved = await resolve_async(effective_query)
            log_resolved(resolved)
            classified = classify(effective_query, resolved, mem)

        # Explicit picks always win over whatever re-extraction guessed
        pc = res.pinned_company
        if pc and resolved.account_filter:
            af = resolved.account_filter
            af.account_name, af.account_id, af.level = pc.account_name, pc.account_id, pc.level
            af.parent_id, af.parent_name = pc.parent_id, pc.parent_name
            af.multiple, af.account_ids = [], []
            resolved.company_ambiguous = False
        if res.pinned_products is not None:
            resolved.product_filters = list(res.pinned_products)
            resolved.product_filter = resolved.product_filters[0] if resolved.product_filters else None
            resolved.product_ambiguous = False
            resolved.product_hierarchy_candidates = []
            for p in resolved.product_filters:
                entity("product", f"{p.display}  (level: {p.level_label})  [your choice]")

    # Stage 4: Parallel agent execution
    step("Stage 4 · Agent execution", f"launching {len(classified.sub_queries or classified.metrics_needed)} agent(s) in parallel…")
    sub_queries = classified.sub_queries
    if not sub_queries:
        sub_queries = [
            SubQuery(metric=m, question=classified.resolved_question or effective_query, id=f"q{i+1}")
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

    # One persistent loop: the DB pool is bound to the loop that created it
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP.run_until_complete(run_async(query, memory, interactive))
