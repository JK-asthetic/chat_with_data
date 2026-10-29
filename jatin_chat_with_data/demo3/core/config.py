"""Settings — reads demo3/.env; a variable already exported in the shell wins."""
import os
from functools import lru_cache
from pathlib import Path

import yaml

_ROOT = Path(__file__).parent.parent
_ENV_FILE = _ROOT / ".env"


def _load_env() -> None:
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


class Settings:
    # ── Postgres ──────────────────────────────────────────────────────────────
    DATABASE_URL:        str = os.getenv("DATABASE_URL", "postgresql://pop:pop_secret@localhost:5432/pop_db")

    # ── ZLLAMA (Zscaler internal LLM) ────────────────────────────────────────
    ZLLAMA_BASE_URL:         str = os.getenv("ZLLAMA_BASE_URL", "https://zllama.corp.zscaler.com")
    ZLLAMA_API_KEY:          str = os.getenv("ZLLAMA_API_KEY", "sk-QrAi3Ej9sVjf-PSYb1ruBA")
    ZLLAMA_SQL_MODEL:        str = os.getenv("ZLLAMA_SQL_MODEL", "claude-sonnet-4-5")  # S5: SQL gen
    ZLLAMA_INSIGHT_MODEL:    str = os.getenv("ZLLAMA_INSIGHT_MODEL",    "claude-haiku-4-5")  # S7: streamed

    ZLLAMA_DECOMPOSER_MODEL: str = os.getenv("ZLLAMA_DECOMPOSER_MODEL", "claude-sonnet-4-5")  # S0: split / follow-up rewrite
    DECOMPOSER_MAX_PARTS:    int = int(os.getenv("DECOMPOSER_MAX_PARTS", "4"))

    # ── Ollama (local — used for SQLCoder SQL generation only) ────────────────
    OLLAMA_HOST:         str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    SQL_MODEL:               str = os.getenv("SQL_MODEL",               "sqlcoder:7b")       # S5: SQL gen

    # ── Pipeline tuning ───────────────────────────────────────────────────────
    MAX_SQL_RETRIES:     int = int(os.getenv("MAX_SQL_RETRIES", "3"))
    SQL_MAX_TOKENS:      int = int(os.getenv("SQL_MAX_TOKENS", "1500"))   # window-function / CTE queries need >512
    DB_TIMEOUT_MS:       int = int(os.getenv("DB_TIMEOUT_MS", "30000"))
    DB_ROW_CAP:          int = int(os.getenv("DB_ROW_CAP", "50000"))
    DEFAULT_LIMIT:       int = int(os.getenv("DEFAULT_LIMIT", "10"))
    COMPANY_SCORE_THRESHOLD: float = float(os.getenv("COMPANY_SCORE_THRESHOLD", "0.75"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_schema() -> dict:
    schema_path = _ROOT / "config" / "schema.yaml"
    return yaml.safe_load(schema_path.read_text())
