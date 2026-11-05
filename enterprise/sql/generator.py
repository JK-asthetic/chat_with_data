"""SQL Generator — calls ZLLAMA Sonnet to generate SQL with validation and caching.

Cost Model:
  Cache hit  -> $0 (instant)
  Cache miss -> ZLLAMA Sonnet (~$0.003) + retry loop + validator
  Exhausted  -> Fallback skeleton (guaranteed valid syntax)
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional
import requests

from core.settings import get_ai
from core.mdl_registry import MetricDefinition
from core.log import step, ok, warn
from pipeline.models import GeneratedSQL, SQLContext
from sql.builder import build_prompt, build_skeleton
from sql.validator import qualify_join_columns, pin_group_by_aliases, validate

logger = logging.getLogger(__name__)

# In-memory NL->SQL cache: sha256(question + metric) -> GeneratedSQL
_SQL_CACHE: dict[str, GeneratedSQL] = {}


def _clean_sql(raw: str) -> str:
    """Strip markdown code fences and extraneous text."""
    sql = raw.strip()
    if "```" in sql:
        parts = sql.split("```")
        for p in parts:
            cleaned = p.strip()
            if cleaned.lower().startswith("sql"):
                cleaned = cleaned[3:].strip()
            if cleaned.upper().startswith(("SELECT", "WITH")):
                sql = cleaned
                break
    lines = [ln for ln in sql.split("\n") if not ln.strip().startswith("--")]
    sql = "\n".join(lines).strip()
    if ";" in sql:
        sql = sql.split(";")[0].strip() + ";"
    return sql


def _cache_key(question: str, metric: str) -> str:
    raw = f"{question.strip().lower()}|{metric.strip().upper()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def generate(
    ctx: SQLContext,
    metric_def: MetricDefinition,
    db_error_feedback: Optional[str] = None,
    db_failed_sql: Optional[str] = None,
) -> GeneratedSQL:
    ai = get_ai()
    key = _cache_key(ctx.normalized_question, ctx.metric)

    # Check cache if no DB error is being retried
    if ai.cache.enabled and not db_error_feedback and key in _SQL_CACHE:
        ok("SQL cache hit", f"metric={ctx.metric}")
        cached = _SQL_CACHE[key]
        return GeneratedSQL(
            sql=cached.sql,
            source="cache",
            attempts=1,
            validation_errors=[],
        )

    step("SQL generation", f"calling {ai.models.sql}  metric={ctx.metric}  intent={ctx.intent}")

    errors: list[str] = [f"DB execution error: {db_error_feedback}"] if db_error_feedback else []
    failed_sql: Optional[str] = db_failed_sql

    for attempt in range(1, ai.pipeline.max_sql_retries + 1):
        err_msg = "\n".join(errors) if errors else None
        prompt = build_prompt(ctx, metric_def, error_feedback=err_msg, failed_sql=failed_sql)

        try:
            base = ai.base_url.rstrip("/")
            resp = requests.post(
                f"{base}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {ai.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": ai.models.sql,
                    "temperature": 0,
                    "max_tokens": ai.pipeline.sql_max_tokens,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a Postgres SQL expert. "
                                "Write correct, concise SQL that answers the question. "
                                "Follow all rules strictly. "
                                "Output ONLY valid Postgres SQL — no markdown fences, no explanation."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=(ai.timeout_connect_s, ai.timeout_read_s),
            )
            resp.raise_for_status()
            choice = resp.json()["choices"][0]
            raw_sql = choice["message"]["content"]
            sql = _clean_sql(raw_sql)
        except Exception as e:
            warn(f"SQL gen attempt {attempt} failed", str(e)[:150])
            logger.warning(f"ZLLAMA SQL generation attempt {attempt} failed: {e}")
            errors = [f"LLM communication error: {str(e)[:150]}"]
            failed_sql = None
            continue

        sql = qualify_join_columns(sql, ctx)
        sql = pin_group_by_aliases(sql)
        val_errors = validate(sql, ctx)

        if not val_errors:
            ok(f"SQL gen attempt {attempt} valid", f"metric={ctx.metric}")
            gen_res = GeneratedSQL(sql=sql, source="llm", attempts=attempt, validation_errors=[])
            if ai.cache.enabled:
                _SQL_CACHE[key] = gen_res
            return gen_res

        warn(f"SQL validation errors (attempt {attempt})", "  |  ".join(val_errors[:3]))
        errors = val_errors
        failed_sql = sql

    # If all retries fail, use deterministic fallback
    warn("SQL generation exhausted retries", "falling back to skeleton SQL")
    skeleton = build_skeleton(ctx)
    return GeneratedSQL(
        sql=skeleton,
        source="fallback",
        attempts=ai.pipeline.max_sql_retries,
        validation_errors=errors,
    )

