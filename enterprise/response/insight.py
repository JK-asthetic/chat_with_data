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


async def generate_insight(result: QueryResult, question: str) -> str:
    """Generate a 2-3 sentence grounded insight from top result rows."""
    if not result.success or not result.rows:
        return ""

    sample_rows = result.rows[:10]
    system_prompt = (
        "You are an enterprise financial analytics assistant. "
        "Summarize the query result in 2-3 concise, strictly factual sentences. "
        "Highlight key leaders, totals, or trends directly from the numbers. "
        "Do NOT invent any data not present in the rows."
    )
    user_prompt = f"Question: {question}\nResult rows (first {len(sample_rows)}):\n{json.dumps(sample_rows, default=str, indent=2)}"

    return _stream(system_prompt, user_prompt, prefix="💡 Insight: ", max_tokens=250)

