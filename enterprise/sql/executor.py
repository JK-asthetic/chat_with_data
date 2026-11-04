"""SQL Executor — runs SQL queries against Postgres or CSV samples in dry-run mode."""
from __future__ import annotations

import time
from typing import Any
from core.db import async_query
from core.settings import get_db
from pipeline.models import QueryResult, SQLContext


async def execute(sql: str, ctx: SQLContext) -> QueryResult:
    """Executes SQL query with performance timing and error handling."""
    t0 = time.perf_counter()
    cfg = get_db()

    try:
        rows = await async_query(sql, table_hint=ctx.primary_table)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        columns = list(rows[0].keys()) if rows else []

        # Apply LIMIT if present in context
        effective_rows = rows[:ctx.limit] if ctx.limit else rows

        if cfg.dry_run and effective_rows:
            # Project only columns requested in group_by and the metric
            wanted_cols = [c for c in ctx.group_by if c in effective_rows[0]]
            metric_candidates = [ctx.metric, f"total_{ctx.metric}", "arr", "adjusted_acv", "arr_change", "downsell", "target", "product_l1_qty", "renewal_risk_score", "churn_amount"]
            for m in metric_candidates:
                if m in effective_rows[0] and m not in wanted_cols:
                    wanted_cols.append(m)
                    break
            if wanted_cols:
                effective_rows = [{c: r.get(c, "") for c in wanted_cols} for r in effective_rows]
                columns = wanted_cols

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
        return QueryResult(
            sql=sql,
            rows=[],
            columns=[],
            row_count=0,
            elapsed_ms=round(elapsed_ms, 2),
            db_error=str(e),
            success=False,
        )
