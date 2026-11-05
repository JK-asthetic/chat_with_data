"""Database access layer — asyncpg pool (async) and psycopg2 (sync read-only)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import Any, Generator

from core.settings import get_db

logger = logging.getLogger(__name__)

_pool: Any = None
_pool_loop: Any = None


@contextmanager
def get_readonly_conn() -> Generator:
    """Yields a psycopg2 readonly connection."""
    import psycopg2
    import psycopg2.extras

    cfg = get_db()
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
    import psycopg2.extras

    with get_readonly_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or None)
            row = cur.fetchone()
            return dict(row) if row else None


def query_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Fetch all rows as list of dicts."""
    import psycopg2.extras

    with get_readonly_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or None)
            return [dict(r) for r in cur.fetchall()]


async def async_query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Async query executor — uses asyncpg connection pool."""
    global _pool, _pool_loop
    loop = asyncio.get_running_loop()
    if _pool is not None and _pool_loop is not loop:
        _pool = None  # created on another (finished) event loop — unusable here
    if _pool is None:
        import asyncpg

        cfg = get_db()
        _pool = await asyncpg.create_pool(
            dsn=cfg.url,
            min_size=cfg.pool_min_size,
            max_size=cfg.pool_max_size,
            command_timeout=cfg.statement_timeout_ms / 1000.0,
        )
        _pool_loop = loop

    async with _pool.acquire() as conn:
        records = await conn.fetch(sql, *(params.values() if params else ()))
        return [dict(r) for r in records]


async def close_pool() -> None:
    global _pool, _pool_loop
    if _pool is not None and _pool_loop is asyncio.get_running_loop():
        await _pool.close()
    _pool = None
    _pool_loop = None


def check_pg_trgm() -> bool:
    """Returns True if pg_trgm extension is installed."""
    try:
        res = query_one("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        return res is not None
    except Exception:
        return False
