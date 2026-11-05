"""SQL Executor — runs SQL queries against Postgres with performance timing."""
from __future__ import annotations

import time
from typing import Any

from core.db import async_query
from core.settings import get_db
from core.log import ok, warn
from pipeline.models import QueryResult, SQLContext


_ROW_CAP = getattr(get_db(), "row_cap", 50000) or 50000


async def execute(sql: str, ctx: SQLContext) -> QueryResult:
    """Executes SQL query with performance timing and error handling."""
    t0 = time.perf_counter()

    try:
        rows = await async_query(sql)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        columns = list(rows[0].keys()) if rows else []
        effective_rows = rows[:_ROW_CAP]                      # the SQL's own LIMIT decides; this is a safety cap

        ok(f"DB query [{ctx.primary_table}]", f"rows={len(effective_rows)}  elapsed={round(elapsed_ms, 2)}ms")

        return QueryResult(
            sql=sql,
            rows=effective_rows,
            columns=columns,
            row_count=len(effective_rows),
            elapsed_ms=round(elapsed_ms, 2),
            db_error=None,
            success=True,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        warn(f"DB query [{ctx.primary_table}] failed", str(e)[:150])
        return QueryResult(
            sql=sql,
            rows=[],
            columns=[],
            row_count=0,
            elapsed_ms=round(elapsed_ms, 2),
            db_error=str(e),
            success=False,
        )
