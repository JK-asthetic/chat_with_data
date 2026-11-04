"""
Stage 0B — LLM Pre-Classifier (runs BEFORE spaCy S1).

Purpose:
  1. Classify the METRIC (ARR / ACV / CHURN / INCR_ARR / QTY) using
     conversation context — spaCy alone can't resolve "same metric" from a follow-up.
  2. Detect INTENT (RANK / AGGREGATE / TREND / LOOKUP / COMPARE / DELTA).
  3. Resolve FOLLOW-UPS — "and for EMEA?" becomes a full self-contained question.
  4. Flag STRATEGIC questions (marketing / budget / planning — no SQL needed).

This is a fast, cheap call (haiku-class, <150 output tokens, ~$0.0003/query).
spaCy S1 then runs on `resolved_question` — a clean, self-contained query —
which dramatically improves entity extraction accuracy.

Input:  raw user question + last N session turns
Output: PreClassification (dataclass)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import requests

from core.config import get_settings
from core.memory import SessionMemory


# ── Output model ──────────────────────────────────────────────────────────────

@dataclass
class PreClassification:
    metric:             str            = "ARR"      # ARR | ACV | NNACV | NACV | CHURN | INCR_ARR | QTY
    intent:             str            = "AGGREGATE" # RANK | AGGREGATE | TREND | LOOKUP | COMPARE | DELTA
    resolved_question:  str            = ""         # full self-contained question for S1
    is_followup:        bool           = False
    is_strategic:       bool           = False
    fiscal_hint:        Optional[str]  = None       # "FY 2026 Q1" if LLM caught it
    confidence:         str            = "high"     # high | medium | low


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a query pre-classifier for a Zscaler ARR analytics system.

METRICS available:
- ARR       Annual Recurring Revenue (snapshot — from data_arr, most common default)
- ACV       Annual Contract Value — total deal/booking value (from data_acv, all deal types)
- NNACV     Net New ACV — ACV excluding renewals (from data_acv, carve_split_type NOT IN Renewal)
- NACV      New ACV target/planning values by product (from data_nacv_target — planning table only)
- CHURN     ARR lost or contracted — use SUM(downsell) (from data_inc_arr, keyed on parent account)
- INCR_ARR  Incremental/Net New ARR — delta per quarter (from data_inc_arr, keyed on parent account)
- QTY       License/seat quantity (from data_quantity)

INTENTS:
- RANK      "top N", "bottom N", "who has the most/least"
- AGGREGATE "total", "breakdown by", "by product/segment/geo"
- TREND     "over time", "by quarter", "trend", "QoQ", "YoY"
- LOOKUP    "what is [company]'s ARR", specific account lookup
- COMPARE   "A vs B", "compare X and Y"
- DELTA     "change", "growth", "increase/decrease since"

FOLLOW-UP resolution rules:
- If the question references a prior context ("same accounts", "and for EMEA?",
  "what about ZPA?", "their ARR"), set is_followup=true and rewrite
  resolved_question as a complete, self-contained question using the history.
- If no prior context is needed, resolved_question = original question (cleaned).

STRATEGIC questions (no SQL): marketing strategy, budget allocation, go-to-market,
  "how should we", "how to optimize", "what is the best approach".

Respond ONLY with valid JSON — no markdown, no explanation:
{
  "metric": "ARR",
  "intent": "RANK",
  "resolved_question": "top 10 accounts by ZIA ARR in EMEA DACH for FY 2026 Q1",
  "is_followup": false,
  "is_strategic": false,
  "fiscal_hint": "FY 2026 Q1",
  "confidence": "high"
}
"""


# ── LLM call ─────────────────────────────────────────────────────────────────

def _call(system: str, user_msg: str) -> str:
    cfg = get_settings()
    try:
        base = cfg.ZLLAMA_BASE_URL.rstrip("/")
        resp = requests.post(
            f"{base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {cfg.ZLLAMA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": cfg.ZLLAMA_INSIGHT_MODEL,   # haiku-class — fast + cheap
                "temperature": 0,
                "max_tokens": 150,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_msg},
                ],
            },
            timeout=(3, 10),   # fail fast — this must not block the pipeline
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""   # graceful fallback — S1 handles everything


# ── Context builder ───────────────────────────────────────────────────────────

def _build_context(question: str, memory: Optional[SessionMemory]) -> str:
    parts: list[str] = []

    if memory:
        recent = memory.prompt_context(3)   # last 3 turns
        if recent:
            history_lines = []
            for t in recent:
                q = t.get("question") or t.get("query", "")
                metric = t.get("entities", {}).get("metric", "")
                account = t.get("entities", {}).get("account", "")
                fiscal = t.get("entities", {}).get("fiscal", "")
                geo = t.get("entities", {}).get("geo", [])
                products = t.get("entities", {}).get("products", [])
                history_lines.append(
                    f"Q: {q}"
                    + (f"  [metric={metric}]" if metric else "")
                    + (f"  [account={account}]" if account else "")
                    + (f"  [fiscal={fiscal}]" if fiscal else "")
                    + (f"  [geo={geo}]" if geo else "")
                    + (f"  [products={products}]" if products else "")
                )
            parts.append("Recent conversation:\n" + "\n".join(history_lines))

    parts.append(f"Current question: {question}")
    return "\n\n".join(parts)


# ── Public entry point ────────────────────────────────────────────────────────

_METRIC_KEYWORDS = {
    # NACV target (planning table) — must come before ACV / NNACV
    "nacv target":        "NACV",
    "new acv target":     "NACV",
    "nacv":               "NACV",

    # NNACV — net new ACV (excludes renewals)
    "net new acv":        "NNACV",
    "nnacv":              "NNACV",
    "new acv":            "NNACV",

    # ACV — booking / deal value (all deal types)
    "acv":                "ACV",
    "annual contract":    "ACV",
    "booking":            "ACV",
    "bookings":           "ACV",

    # ACV sub-types — these all route to data_acv with carve_split_type filtering
    # Classifier returns ACV; deal motion (new logo / upsell) is captured by NER order_type
    "new logo":           "ACV",
    "new logos":          "ACV",
    "new customer":       "ACV",
    "new customers":      "ACV",
    "new business":       "ACV",
    "new account":        "ACV",
    "new accounts":       "ACV",
    "upsell acv":         "ACV",
    "expansion acv":      "ACV",
    "cross sell acv":     "ACV",
    "new to product":     "ACV",
    "renewal acv":        "ACV",

    # Churn / downsell — routes to data_inc_arr
    "churn":              "CHURN",
    "downsell":           "CHURN",
    "churned":            "CHURN",
    "contraction":        "CHURN",
    "lost arr":           "CHURN",

    # Incremental / net new ARR — routes to data_inc_arr
    "incremental arr":    "INCR_ARR",
    "net new arr":        "INCR_ARR",
    "net new":            "INCR_ARR",
    "inc arr":            "INCR_ARR",
    "new arr":            "INCR_ARR",
    "delta arr":          "INCR_ARR",
    "incremental":        "INCR_ARR",

    # Quantity / seats
    "qty":                "QTY",
    "quantity":           "QTY",
    "seats":              "QTY",
    "seat count":         "QTY",
    "licenses":           "QTY",
    "license count":      "QTY",
    "units":              "QTY",
}

_STRATEGIC_KW = (
    "how should", "how to", "how can", "optimize", "optimise",
    "marketing by", "budget", "go to market", "channel mix",
    "what strategy", "recommend", "best approach", "playbook",
    "improve retention", "reduce churn strategy",
)


def _fast_metric(question: str) -> Optional[str]:
    """Keyword shortcut — avoids the LLM call for the most obvious cases."""
    q = question.lower()
    for kw, metric in _METRIC_KEYWORDS.items():
        if kw in q:
            return metric
    return None


def classify(question: str, memory: Optional[SessionMemory] = None) -> PreClassification:
    """
    Run the LLM pre-classifier on `question` with optional session context.

    Returns PreClassification. On any failure, returns a safe default so the
    pipeline continues normally via spaCy S1.
    """
    # Fast-path: obvious strategic question — skip LLM
    q_low = question.lower()
    if any(kw in q_low for kw in _STRATEGIC_KW):
        return PreClassification(
            resolved_question=question,
            is_strategic=True,
            confidence="high",
        )

    # Fast-path metric detection (avoids LLM for unambiguous cases)
    fast_metric = _fast_metric(question)

    # Only call LLM when: follow-up likely, metric ambiguous, or complex question
    needs_llm = (
        memory and bool(memory.prompt_context(1))  # there IS prior context
        or "same" in q_low
        or "their" in q_low
        or "those" in q_low
        or "it" in q_low.split()
        or "?" not in question and len(question.split()) < 6  # very short = likely followup
    )

    if needs_llm:
        ctx = _build_context(question, memory)
        raw = _call(_SYSTEM, ctx)

        if raw:
            try:
                raw_clean = raw.strip()
                if raw_clean.startswith("```"):
                    raw_clean = "\n".join(raw_clean.split("\n")[1:]).rstrip("`").strip()
                data = json.loads(raw_clean)
                return PreClassification(
                    metric            = data.get("metric", fast_metric or "ARR"),
                    intent            = data.get("intent", "AGGREGATE"),
                    resolved_question = data.get("resolved_question", question) or question,
                    is_followup       = bool(data.get("is_followup", False)),
                    is_strategic      = bool(data.get("is_strategic", False)),
                    fiscal_hint       = data.get("fiscal_hint"),
                    confidence        = data.get("confidence", "medium"),
                )
            except (json.JSONDecodeError, KeyError):
                pass   # fall through to default

    # Default: no LLM needed or LLM failed — safe passthrough
    return PreClassification(
        metric            = fast_metric or "ARR",
        intent            = "AGGREGATE",
        resolved_question = question,
        is_followup       = False,
        is_strategic      = False,
        confidence        = "high" if fast_metric else "medium",
    )
