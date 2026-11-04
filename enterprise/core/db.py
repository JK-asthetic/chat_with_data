"""Database access layer — asyncpg pool, psycopg2 fallback, and dry-run CSV loader.

When dry_run=True (default when no database is connected), queries are served
from the local CSV sample files in the data directory using standard library csv.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import csv
import logging
from pathlib import Path
from typing import Any, Generator, Optional

from core.settings import get_db

logger = logging.getLogger(__name__)

# CSV name mappings for sample data
_TABLE_CSV_MAP = {
    "data_arr": "data_arr.csv",
    "data_acv": "data_acv.csv",
    "data_inc_arr": "data-inc-arrcsv.csv",
    "data_nacv_target": "data-nacv_target.csv",
    "data_quantity": "data-quantity.csv",
    "dim_account": "dim_acount.csv",
    "data_renewal_risk": "data_renewal_risk.csv",
    "data_churn_reason": "data-churn-reason.csv",
}

_pool: Any = None
_csv_cache: dict[str, list[dict[str, Any]]] = {}


def _load_csv_for_table(table_name: str) -> list[dict[str, Any]]:
    """Load a CSV file for a table in dry-run mode using standard library csv."""
    if table_name in _csv_cache:
        return _csv_cache[table_name]

    cfg = get_db()
    data_dir = cfg.data_dir
    filename = _TABLE_CSV_MAP.get(table_name, f"{table_name}.csv")
    csv_path = data_dir / filename

    if not csv_path.exists():
        logger.warning(f"Dry-run CSV not found at: {csv_path}")
        return []

    rows: list[dict[str, Any]] = []
    try:
        with open(csv_path, mode="r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i >= cfg.row_cap:
                    break
                rows.append(dict(row))
        _csv_cache[table_name] = rows
        return rows
    except Exception as e:
        logger.error(f"Error reading dry-run CSV {csv_path}: {e}")
        return []


@contextmanager
def get_readonly_conn() -> Generator:
    """Yields a psycopg2 readonly connection if DB is enabled."""
    cfg = get_db()
    if cfg.dry_run:
        raise RuntimeError("Database connection attempted while in dry-run mode.")

    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(
        cfg.url,
        connect_timeout=cfg.connect_timeout_s,
        options=f"-c statement_timeout={cfg.statement_timeout_ms}",
    )
    conn.set_session(readonly=True, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def query_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Fetch a single row as dict."""
    cfg = get_db()
    if cfg.dry_run:
        sql_lower = sql.lower()
        for tbl in _TABLE_CSV_MAP:
            if tbl in sql_lower:
                rows = _load_csv_for_table(tbl)
                if rows:
                    return rows[0]
        return None

    import psycopg2.extras
    with get_readonly_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or {})
            row = cur.fetchone()
            return dict(row) if row else None


def query_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Fetch all rows as list of dicts."""
    cfg = get_db()
    if cfg.dry_run:
        sql_lower = sql.lower()
        for tbl in _TABLE_CSV_MAP:
            if tbl in sql_lower:
                rows = _load_csv_for_table(tbl)
                return rows[:25]
        return []

    import psycopg2.extras
    with get_readonly_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or {})
            return [dict(r) for r in cur.fetchall()]


async def async_query(sql: str, params: dict[str, Any] | None = None, table_hint: str = "data_arr") -> list[dict[str, Any]]:
    """Async query executor — uses asyncpg pool in prod, or CSV in dry-run."""
    cfg = get_db()
    if cfg.dry_run:
        rows = _load_csv_for_table(table_hint)
        if not rows:
            sql_lower = sql.lower()
            for tbl in _TABLE_CSV_MAP:
                if tbl in sql_lower:
                    rows = _load_csv_for_table(tbl)
                    break
        return rows[:25]

    global _pool
    if _pool is None:
        import asyncpg
        _pool = await asyncpg.create_pool(
            dsn=cfg.url,
            min_size=cfg.pool_min_size,
            max_size=cfg.pool_max_size,
            command_timeout=cfg.statement_timeout_ms / 1000.0,
        )

    async with _pool.acquire() as conn:
        records = await conn.fetch(sql, *(params.values() if params else ()))
        return [dict(r) for r in records]


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def check_pg_trgm() -> bool:
    """Returns True if pg_trgm extension is installed."""
    cfg = get_db()
    if cfg.dry_run:
        return False
    try:
        res = query_one("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        return res is not None
    except Exception:
        return False
