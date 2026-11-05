"""
Pipeline Classifier — the LLM brain of the pipeline.

One Haiku call decides:
  1. Which metric(s) the question needs → routes to agents
  2. Intent (RANK/LOOKUP/AGGREGATE/TREND/COMPARE/DELTA)
  3. Is this a follow-up? → rewrite as standalone
  4. Is this strategic? → bypass SQL pipeline
  5. Remaining ambiguities after entity resolution
  6. Split into sub_queries for multi-metric questions

Cost: Haiku (~$0.0001 per call) — cheap judgment layer.
SQL accuracy: handled by Sonnet in each metric agent.

Design notes:
- The prompt explicitly lists available metrics so the LLM never hallucinates
  metric names.
- Entity resolution happens *before* this call; the classifier only decides
  routing, not entity values.
- If the LLM call fails for any reason the classifier falls back to a safe
  default (ARR / AGGREGATE) so the pipeline never hard-crashes.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from core.mdl_registry import get_registry
from core.settings import get_ai
from core.log import step, ok, warn
from pipeline.memory import SessionMemory
from pipeline.models import ClassifiedQuery, Intent, ResolvedEntities, SubQuery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strategic-question keyword shortcut
# ---------------------------------------------------------------------------

_STRATEGIC_KW: tuple[str, ...] = (
    "how should",
    "how to",
    "optimize",
    "best approach",
    "what strategy",
    "recommend",
    "suggest",
    "go to market",
    "budget",
    "channel mix",
    "playbook",
)
"""Lowercase phrases that always classify a question as strategic without an LLM call."""


def _is_strategic_by_keyword(text: str) -> bool:
    """Return True if *text* contains any strategic keyword.

    Args:
        text: The (lowercased) user question.

    Returns:
        ``True`` when the question matches a strategic keyword.
    """
    lower = text.lower()
    return any(kw in lower for kw in _STRATEGIC_KW)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_classifier_prompt(
    query: str,
    resolved: ResolvedEntities,
    memory: SessionMemory,
) -> str:
    """Build the structured classification prompt sent to the LLM.

    The prompt is intentionally verbose to constrain the LLM output tightly.
    It injects:
    - Available metric catalogue (from MDL registry)
    - Already-resolved entity values (so the LLM never re-extracts entities)
    - Recent session context (for follow-up detection)
    - Strict JSON output schema

    Args:
        query:    The user's question (possibly follow-up rewritten by memory).
        resolved: Fully resolved entity bag from extraction stage.
        memory:   Session memory for multi-turn context.

    Returns:
        A prompt string ready to send to the LLM.
    """
    # -- Available metrics from registry ------------------------------------
    registry = get_registry()
    metric_lines: list[str] = []
    for name, defn in registry.items():
        keywords: list[str] = getattr(defn, "keywords", []) or []
        kw_str = ", ".join(keywords[:6]) if keywords else "—"
        metric_lines.append(f"  - {name}: {kw_str}")
    metrics_catalogue = "\n".join(metric_lines) if metric_lines else "  - ARR: annual recurring revenue"

    # -- Resolved entities summary -----------------------------------------
    ext = resolved.extracted
    entity_parts: list[str] = []

    if resolved.account_filter and resolved.account_filter.account_name:
        entity_parts.append(f"account={resolved.account_filter.account_name!r}")
    elif ext.accounts_raw:
        entity_parts.append(f"accounts_raw={ext.accounts_raw}")

    if resolved.fiscal:
        f = resolved.fiscal
        label = f.fiscal_quarter_label or f.fiscal_year_label or f"FY{f.fy}"
        entity_parts.append(f"fiscal={label!r}")

    if resolved.product_filter:
        entity_parts.append(f"product={resolved.product_filter.path}")

    if resolved.geo_filter:
        entity_parts.append(f"geo={resolved.geo_filter.col}={resolved.geo_filter.value!r}")

    if resolved.segment_filter:
        entity_parts.append(f"segment={resolved.segment_filter!r}")

    if ext.limit_n and ext.limit_n != 10:
        entity_parts.append(f"top_n={ext.limit_n}")

    entity_summary = "; ".join(entity_parts) if entity_parts else "(none resolved)"

    # -- Resolved metric hint ----------------------------------------------
    metric_hint = resolved.metric.name if resolved.metric else ext.metric_raw or "ARR"

    # -- Session context ---------------------------------------------------
    ctx_turns = memory.prompt_context(n=3)
    if ctx_turns:
        ctx_lines = json.dumps(ctx_turns, indent=2)
    else:
        ctx_lines = "  (no prior turns)"

    # -- Ambiguities so far ------------------------------------------------
    existing_ambiguities = resolved.ambiguities or []

    # -- Build prompt ------------------------------------------------------
    prompt = f"""You are a classification engine for an enterprise analytics assistant.
Your ONLY job is to output a single JSON object — no prose, no markdown fences.

## AVAILABLE METRICS
{metrics_catalogue}

## ALREADY RESOLVED ENTITIES (do NOT re-extract these)
{entity_summary}

## LIKELY METRIC (from extraction stage)
{metric_hint}

## RECENT SESSION CONTEXT
{ctx_lines}

## USER QUESTION
{query!r}

## KNOWN AMBIGUITIES (already flagged by extraction stage)
{json.dumps(existing_ambiguities)}

## YOUR TASK
Analyze the question and output EXACTLY this JSON schema:

{{
  "metrics_needed": ["ARR"],          // list of canonical metric names from AVAILABLE METRICS
  "intent": "AGGREGATE",              // one of: RANK, LOOKUP, AGGREGATE, TREND, COMPARE, DELTA, RISK
  "is_followup": false,               // true if question references prior turns
  "resolved_question": null,          // standalone rewrite if is_followup=true, else null
  "is_strategic": false,              // true for open-ended strategy / advisory questions
  "sub_queries": [],                  // list of {{metric, question, id}} for multi-metric questions
  "ambiguities": []                   // NEW ambiguities you detect beyond the already-flagged ones
}}

## RULES
- metrics_needed: include ONLY metrics from the AVAILABLE METRICS list.  Default to ["ARR"].
- intent RANK: "top N", "highest", "lowest", "ranking" questions.
- intent LOOKUP: single entity value retrieval.
- intent TREND: "over time", "quarterly", "trend", "trajectory" questions.
- intent COMPARE: explicitly comparing two entities or periods.
- intent DELTA: "change", "growth", "delta", "diff" between two periods.
- intent RISK: churn, at-risk, health-score questions.
- is_followup=true only when pronouns or ordinals clearly reference prior results.
- When is_followup=true you MUST provide resolved_question as a full standalone question.
- sub_queries: only populate when >1 metric is genuinely needed; each entry must map to one metric.
- is_strategic=true for advisory, budget, strategy, playbook, go-to-market questions.
- Output ONLY the JSON object. No explanation, no markdown.
"""
    return prompt


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(prompt: str) -> str:
    """Send *prompt* to the configured Haiku model and return the raw text response.

    Args:
        prompt: The fully assembled classifier prompt.

    Returns:
        Raw response text from the LLM.

    Raises:
        requests.HTTPError: On non-2xx HTTP responses.
        requests.Timeout:   If the LLM takes too long.
    """
    ai_cfg = get_ai()
    base = ai_cfg.base_url.rstrip("/")
    if not base:
        raise ValueError("ZLLAMA base_url is empty")

    endpoint = f"{base}/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ai_cfg.api_key}",
    }

    payload: dict[str, Any] = {
        "model": ai_cfg.models.classifier,
        "max_tokens": 512,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }

    response = requests.post(
        endpoint,
        headers=headers,
        json=payload,
        timeout=(ai_cfg.timeout_connect_s, ai_cfg.timeout_read_s),
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0].get("message", {}).get("content", "")


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Extract and parse the JSON object from *raw* LLM output.

    The LLM sometimes wraps output in markdown fences — this strips them.

    Args:
        raw: Raw LLM response text.

    Returns:
        Parsed dict.

    Raises:
        ValueError: If no valid JSON object can be found.
    """
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?", "", raw).strip()

    # Locate the first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response: {raw[:200]!r}")

    return json.loads(match.group(0))


def _build_fallback(
    query: str,
    resolved: ResolvedEntities,
    reason: str,
) -> ClassifiedQuery:
    """Return a safe default ClassifiedQuery when the LLM call fails.

    Args:
        query:    The original user question.
        resolved: Resolved entities (used to infer metric from extraction).
        reason:   Short description of why fallback was triggered (for logging).

    Returns:
        A ClassifiedQuery with conservative defaults.
    """
    logger.warning("Classifier fallback triggered: %s", reason)
    q_upper = query.upper()
    metrics: list[str] = []
    registry = get_registry()
    for m_name, m_def in registry.items():
        if re.search(r"\b" + re.escape(m_name) + r"\b", q_upper):
            if m_name not in metrics:
                metrics.append(m_name)
        elif any(re.search(r"\b" + re.escape(kw.upper()) + r"\b", q_upper) for kw in m_def.keywords if len(kw) > 3):
            if m_name not in metrics:
                metrics.append(m_name)

    if not metrics:
        metrics = [resolved.metric.name if resolved.metric else "ARR"]

    sub_queries = [
        SubQuery(metric=m, question=query, id=f"q{i+1}")
        for i, m in enumerate(metrics)
    ] if len(metrics) > 1 else []

    return ClassifiedQuery(
        original_query=query,
        metrics_needed=metrics,
        intent=resolved.extracted.intent,
        is_followup=False,
        resolved_question=None,
        is_strategic=False,
        sub_queries=sub_queries,
        ambiguities=resolved.ambiguities or [],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(
    query: str,
    resolved: ResolvedEntities,
    memory: SessionMemory,
) -> ClassifiedQuery:
    """Classify a user question using the LLM brain (Haiku).

    Steps:
    1. Keyword shortcut: if the question is strategic, skip the LLM.
    2. Build the classifier prompt.
    3. Call the LLM.
    4. Parse the JSON response.
    5. Fall back gracefully on any error.

    Args:
        query:    The user's question (may already be reference-resolved by memory).
        resolved: Fully resolved entity bag from the extraction stage.
        memory:   Session memory for multi-turn context injection.

    Returns:
        :class:`ClassifiedQuery` with routing decisions populated.
    """
    # -- Fast strategic shortcut -------------------------------------------
    if _is_strategic_by_keyword(query):
        ok("Classifier shortcut", "strategic keyword match, no LLM call needed")
        logger.debug("Classifier: strategic keyword match, bypassing LLM.")
        metric = resolved.metric.name if resolved.metric else "ARR"
        return ClassifiedQuery(
            original_query=query,
            metrics_needed=[metric],
            intent=Intent.AGGREGATE,
            is_followup=False,
            resolved_question=None,
            is_strategic=True,
            sub_queries=[],
            ambiguities=resolved.ambiguities or [],
        )

    # -- Build prompt -------------------------------------------------------
    try:
        step("Classifier", "building prompt…")
        prompt = build_classifier_prompt(query, resolved, memory)
    except Exception as exc:  # pragma: no cover
        return _build_fallback(query, resolved, f"prompt build error: {exc}")

    # -- LLM call -----------------------------------------------------------
    try:
        step("Classifier LLM", f"calling {get_ai().models.classifier}…")
        raw_response = _call_llm(prompt)
        logger.debug("Classifier LLM raw: %s", raw_response[:300])
    except Exception as exc:
        warn("Classifier LLM failed", str(exc)[:150])
        return _build_fallback(query, resolved, f"LLM call error: {exc}")

    # -- Parse response -----------------------------------------------------
    try:
        data = _parse_llm_json(raw_response)
    except Exception as exc:
        return _build_fallback(query, resolved, f"JSON parse error: {exc}")

    # -- Build SubQuery list ------------------------------------------------
    raw_sub: list[dict[str, Any]] = data.get("sub_queries", []) or []
    sub_queries: list[SubQuery] = []
    for i, sq in enumerate(raw_sub, start=1):
        try:
            sub_queries.append(
                SubQuery(
                    metric=sq.get("metric", "ARR"),
                    question=sq.get("question", query),
                    id=sq.get("id", f"q{i}"),
                )
            )
        except Exception:
            pass  # malformed sub_query entry — skip silently

    # -- Resolve intent enum ------------------------------------------------
    intent_raw: str = str(data.get("intent", "AGGREGATE")).upper()
    try:
        intent = Intent(intent_raw)
    except ValueError:
        intent = Intent.AGGREGATE

    # -- Merge ambiguities --------------------------------------------------
    llm_ambiguities: list[str] = data.get("ambiguities", []) or []
    all_ambiguities = list(dict.fromkeys(list(resolved.ambiguities or []) + llm_ambiguities))

    # -- Build result -------------------------------------------------------
    try:
        classified = ClassifiedQuery(
            original_query=query,
            metrics_needed=data.get("metrics_needed") or ["ARR"],
            intent=intent,
            is_followup=bool(data.get("is_followup", False)),
            resolved_question=data.get("resolved_question") or None,
            is_strategic=bool(data.get("is_strategic", False)),
            sub_queries=sub_queries,
            ambiguities=all_ambiguities,
        )
    except Exception as exc:
        return _build_fallback(query, resolved, f"model validation error: {exc}")

    ok("Classifier done",
       f"metrics={classified.metrics_needed}  intent={classified.intent}  "
       f"followup={classified.is_followup}  strategic={classified.is_strategic}")
    logger.info(
        "Classifier: metrics=%s intent=%s followup=%s strategic=%s",
        classified.metrics_needed,
        classified.intent,
        classified.is_followup,
        classified.is_strategic,
    )
    return classified
