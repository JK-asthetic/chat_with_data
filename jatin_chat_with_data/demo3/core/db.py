"""Postgres connection — readonly sessions with statement timeout."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras

from core.config import get_settings


@contextmanager
def get_readonly_conn() -> Generator:
    """Yields a read-only psycopg2 connection with statement timeout."""
    cfg = get_settings()
    conn = psycopg2.connect(
        cfg.DATABASE_URL,
        connect_timeout=10,
        options=f"-c statement_timeout={cfg.DB_TIMEOUT_MS}",
    )
    conn.set_session(readonly=True, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def query_one(sql: str, params: dict | None = None) -> dict | None:
    """Fetch a single row as dict."""
    with get_readonly_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or {})
            row = cur.fetchone()
            return dict(row) if row else None


def query_all(sql: str, params: dict | None = None) -> list[dict]:
    """Fetch all rows as list of dicts."""
    with get_readonly_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or {})
            return [dict(r) for r in cur.fetchall()]


def check_pg_trgm() -> bool:
    """Returns True if pg_trgm extension is installed."""
    try:
        result = query_one(
            "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"
        )
        return result is not None
    except Exception:
        return False
