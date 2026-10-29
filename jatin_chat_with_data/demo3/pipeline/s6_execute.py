"""
Stage 6 — Postgres Execution.

- Read-only session (statement_timeout from settings)
- Hard row cap (DB_ROW_CAP)
- Injects LIMIT if missing as safety net (validator should have caught it)
- Returns QueryResult with rows, columns, elapsed_ms
"""
from __future__ import annotations

import re
import time

import psycopg2
import psycopg2.extras

from core.config import get_settings
from pipeline.models import QueryResult


def _ensure_limit(sql: str, limit: int) -> str:
    """Append LIMIT if the SQL somehow slipped through without one."""
    if "LIMIT" not in sql.upper():
        return sql.rstrip(";").rstrip() + f"\nLIMIT {limit};"
    return sql


def execute(sql: str, limit: int = 10) -> QueryResult:
    """
    Execute SQL against the live pop_db (readonly).
    Returns QueryResult — never raises; errors go into db_error field.
    """
    cfg = get_settings()
    sql = _ensure_limit(sql, min(limit, cfg.DB_ROW_CAP))

    t0 = time.perf_counter()
    try:
        conn = psycopg2.connect(
            cfg.DATABASE_URL,
            connect_timeout=10,
            options=f"-c statement_timeout={cfg.DB_TIMEOUT_MS}",
        )
        conn.set_session(readonly=True, autocommit=True)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            raw_rows = cur.fetchmany(cfg.DB_ROW_CAP)
            columns  = [d[0] for d in cur.description] if cur.description else []

        conn.close()
        elapsed = round((time.perf_counter() - t0) * 1000, 1)

        rows = [dict(r) for r in raw_rows]
        return QueryResult(
            sql=sql,
            rows=rows,
            columns=columns,
            row_count=len(rows),
            elapsed_ms=elapsed,
            success=True,
        )

    except psycopg2.errors.QueryCanceled:
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        return QueryResult(
            sql=sql, elapsed_ms=elapsed,
            db_error=f"Query timed out after {cfg.DB_TIMEOUT_MS // 1000}s — try adding filters.",
        )
    except psycopg2.Error as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        # Surface the Postgres error cleanly (no stack trace, no internal path)
        return QueryResult(
            sql=sql, elapsed_ms=elapsed,
            db_error=str(e).split("\n")[0],   # first line only
        )
    except Exception as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        return QueryResult(sql=sql, elapsed_ms=elapsed, db_error=str(e))
