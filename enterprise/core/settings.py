"""Settings — loads config/db.yaml, config/ai.yaml, and config/schema.yaml separately.

Environment variables always override YAML values (12-factor pattern).
Usage:
    from core.settings import get_db, get_ai, get_schema
    db = get_db()
    ai = get_ai()
    schema = get_schema()
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field

_ROOT = Path(__file__).parent.parent
_DB_CONFIG = _ROOT / "config" / "db.yaml"
_AI_CONFIG = _ROOT / "config" / "ai.yaml"
_SCH_CONFIG = _ROOT / "config" / "schema.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class DBSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "pop_db"
    user: str = "pop"
    password: str = "pop_secret"
    pool_min_size: int = 2
    pool_max_size: int = 10
    statement_timeout_ms: int = 30000
    row_cap: int = 50000
    connect_timeout_s: int = 10
    dry_run: bool = True
    dry_run_data_path: str = "../jatin_chat_with_data/demo3/data"

    @property
    def url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def data_dir(self) -> Path:
        resolved = (_ROOT / self.dry_run_data_path).resolve()
        if not resolved.exists():
            # Alternative fallback path if running from different cwd
            alt = Path("c:/Users/jatin/Documents/chat_with_data/jatin_chat_with_data/demo3/data").resolve()
            if alt.exists():
                return alt
        return resolved


class ModelConfig(BaseModel):
    classifier: str = "claude-haiku-4-5"
    validator: str = "claude-haiku-4-5"
    sql: str = "claude-sonnet-4-5"
    insight: str = "claude-haiku-4-5"


class CacheConfig(BaseModel):
    enabled: bool = True
    max_entries: int = 500
    ttl_seconds: int = 3600


class PipelineConfig(BaseModel):
    max_sql_retries: int = 3
    sql_max_tokens: int = 1500
    default_limit: int = 10
    company_score_threshold: float = 0.75
    decomposer_max_parts: int = 4


class AISettings(BaseModel):
    provider: str = "zllama"
    base_url: str = "https://zllama.corp.zscaler.com"
    api_key: str = ""
    timeout_connect_s: int = 5
    timeout_read_s: int = 45
    models: ModelConfig = Field(default_factory=ModelConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)


@lru_cache(maxsize=1)
def get_db() -> DBSettings:
    raw = _load_yaml(_DB_CONFIG)
    db_raw = raw.get("database", {})
    dry_raw = raw.get("dry_run", {})

    settings = DBSettings(
        host=os.getenv("DB_HOST", db_raw.get("host", "localhost")),
        port=int(os.getenv("DB_PORT", db_raw.get("port", 5432))),
        name=os.getenv("DB_NAME", db_raw.get("name", "pop_db")),
        user=os.getenv("DB_USER", db_raw.get("user", "pop")),
        password=os.getenv("DB_PASSWORD", db_raw.get("password", "pop_secret")),
        pool_min_size=int(db_raw.get("pool_min_size", 2)),
        pool_max_size=int(db_raw.get("pool_max_size", 10)),
        statement_timeout_ms=int(db_raw.get("statement_timeout_ms", 30000)),
        row_cap=int(db_raw.get("row_cap", 50000)),
        connect_timeout_s=int(db_raw.get("connect_timeout_s", 10)),
        dry_run=os.getenv("DRY_RUN", str(dry_raw.get("enabled", True))).lower() == "true",
        dry_run_data_path=dry_raw.get("data_path", "../jatin_chat_with_data/demo3/data"),
    )
    return settings


@lru_cache(maxsize=1)
def get_ai() -> AISettings:
    raw = _load_yaml(_AI_CONFIG)
    zl = raw.get("zllama", {})
    models_raw = raw.get("models", {})
    pipe_raw = raw.get("pipeline", {})
    cache_raw = raw.get("cache", {})

    return AISettings(
        provider=raw.get("provider", "zllama"),
        base_url=os.getenv("ZLLAMA_BASE_URL", zl.get("base_url", "https://zllama.corp.zscaler.com")),
        api_key=os.getenv("ZLLAMA_API_KEY", zl.get("api_key", "sk-niaqj-lRKq--wNtZMNGlog")),
        timeout_connect_s=int(zl.get("timeout_connect_s", 5)),
        timeout_read_s=int(zl.get("timeout_read_s", 45)),
        models=ModelConfig(
            classifier=models_raw.get("classifier", "claude-haiku-4-5"),
            validator=models_raw.get("validator", "claude-haiku-4-5"),
            sql=models_raw.get("sql", "claude-sonnet-4-5"),
            insight=models_raw.get("insight", "claude-haiku-4-5"),
        ),
        pipeline=PipelineConfig(
            max_sql_retries=int(pipe_raw.get("max_sql_retries", 3)),
            sql_max_tokens=int(pipe_raw.get("sql_max_tokens", 1500)),
            default_limit=int(pipe_raw.get("default_limit", 10)),
            company_score_threshold=float(pipe_raw.get("company_score_threshold", 0.75)),
            decomposer_max_parts=int(pipe_raw.get("decomposer_max_parts", 4)),
        ),
        cache=CacheConfig(
            enabled=cache_raw.get("enabled", True),
            max_entries=int(cache_raw.get("max_entries", 500)),
            ttl_seconds=int(cache_raw.get("ttl_seconds", 3600)),
        ),
    )


@lru_cache(maxsize=1)
def get_schema() -> dict[str, Any]:
    return _load_yaml(_SCH_CONFIG)

