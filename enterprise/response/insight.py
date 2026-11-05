"""Insight Generator — generates concise, grounded summaries of query results.

Uses Haiku model (~$0.0001 per call) to keep pipeline costs minimal.
"""
from __future__ import annotations

import json
import logging
import requests
from typing import Optional

from core.settings import get_ai
from pipeline.models import QueryResult

logger = logging.getLogger(__name__)


def _stream(system: str, user: str, prefix: str = "💡 Insight: ", max_tokens: int = 300) -> str:
    """Stream response tokens to stdout for interactive feel. Returns complete string."""
    ai = get_ai()
    base = ai.base_url.rstrip("/")
    collected = []

    try:
        resp = requests.post(
            f"{base}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {ai.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": ai.models.insight,
                "temperature": 0,
                "max_tokens": max_tokens,
                "stream": True,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            stream=True,
            timeout=(ai.timeout_connect_s, ai.timeout_read_s),
        )
        resp.raise_for_status()

        print(f"\n  {prefix}", end="", flush=True)
        for line in resp.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if decoded.startswith("data: "):
                data_str = decoded[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    token = chunk["choices"][0]["delta"].get("content", "")
                    print(token, end="", flush=True)
                    collected.append(token)
                except Exception:
                    continue
        print("\n")
        return "".join(collected).strip()
    except Exception as e:
        logger.warning(f"Failed to stream insight: {e}")
        return ""


def _money(v: float) -> str:
    a = abs(v)
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{'-' if v < 0 else ''}{a / div:,.2f}{unit}"
    return f"{v:,.0f}"


def _facts(result: QueryResult) -> str:
    """Totals / leaders computed in code — the LLM restates these instead of doing arithmetic."""
    rows = result.rows
    cols = result.columns or (list(rows[0].keys()) if rows else [])
    def as_num(v):
        try:
            return float(v) if v is not None and not isinstance(v, bool) else None
        except (TypeError, ValueError):
            return None
    numeric = [c for c in cols if any(as_num(r.get(c)) is not None for r in rows)
               and not any(isinstance(r.get(c), str) and as_num(r.get(c)) is None and r.get(c) for r in rows)]
    labels = [c for c in cols if c not in numeric]
    label = lambda r: " / ".join(str(r.get(c) if r.get(c) is not None else "(none)") for c in labels) or "total"
    is_ratio = lambda c: any(t in c.lower() for t in ("pct", "percent", "rate", "arpu", "ratio", "avg", "share"))
    out = [f"rows: {result.row_count}" + (" (all rows below)" if result.row_count <= len(rows) else "")]
    for c in numeric:
        vals = [(as_num(r.get(c)), r) for r in rows if as_num(r.get(c)) is not None]
        if not vals:
            continue
        hi, lo = max(vals, key=lambda x: x[0]), min(vals, key=lambda x: x[0])
        line = f"{c}: highest {label(hi[1])} = {_money(hi[0])}; lowest {label(lo[1])} = {_money(lo[0])}"
        if not is_ratio(c) and len(vals) > 1 and "fiscal_quarter" not in labels and "fiscal_month" not in labels:
            line += f"; sum over rows = {_money(sum(v for v, _ in vals))}"
        out.append(line)
    return "\n".join(out)


async def generate_insight(result: QueryResult, question: str) -> str:
    """Generate a 2-3 sentence grounded insight; every figure comes from code-computed facts or the rows."""
    if not result.success or not result.rows:
        return ""

    sample_rows = result.rows[:15]
    system_prompt = (
        "You are an enterprise financial analytics assistant. "
        "Summarize the query result in 2-3 concise, strictly factual sentences. "
        "Use ONLY figures that appear in FACTS or in the rows, written exactly as in FACTS (K = thousand, M = million, B = billion). "
        "Never add, subtract or re-scale numbers yourself; never state a total that is not in FACTS. "
        "Rows with an empty/(none) label are unassigned data, not a product or company."
    )
    user_prompt = (
        f"Question: {question}\n"
        f"FACTS (computed exactly):\n{_facts(result)}\n"
        f"Result rows (first {len(sample_rows)}):\n{json.dumps(sample_rows, default=str, indent=2)}"
    )

    return _stream(system_prompt, user_prompt, prefix="💡 Insight: ", max_tokens=250)
