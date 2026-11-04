"""Structured pipeline error types with phase tagging for smarter retry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PipelineError:
    phase:       str             # "S5_GENERATE" | "S6_EXECUTE" | "S5_VALIDATE"
    code:        str             # "SQL_SYNTAX" | "FORBIDDEN_TABLE" | "DB_ERROR" | "VALIDATOR_FAIL"
    message:     str
    dialect_sql: Optional[str] = None   # the SQL that caused the error
    attempt:     int            = 1


# Canonical codes
SYNTAX_ERROR    = "SQL_SYNTAX"
FORBIDDEN_TABLE = "FORBIDDEN_TABLE"
FORBIDDEN_COL   = "FORBIDDEN_COLUMN"
DB_ERROR        = "DB_ERROR"
VALIDATOR_FAIL  = "VALIDATOR_FAIL"
FALLBACK_USED   = "FALLBACK_USED"


def s5_error(code: str, message: str, sql: str | None = None, attempt: int = 1) -> PipelineError:
    return PipelineError(phase="S5_GENERATE", code=code, message=message, dialect_sql=sql, attempt=attempt)


def s6_error(message: str, sql: str | None = None) -> PipelineError:
    return PipelineError(phase="S6_EXECUTE", code=DB_ERROR, message=message, dialect_sql=sql)


def format_retry_hint(err: PipelineError) -> str:
    """One-line hint for the LLM retry prompt explaining what went wrong."""
    hints = {
        SYNTAX_ERROR:    "The previous SQL had a syntax error. Fix the SQL syntax.",
        FORBIDDEN_TABLE: "The previous SQL referenced a retired or forbidden table. Use data_arr (ARR), data_acv (ACV), data_inc_arr (INCR_ARR/CHURN), data_nacv_target (NACV), or data_quantity (QTY).",
        FORBIDDEN_COL:   "The previous SQL used a column that does not exist. Check the DDL.",
        DB_ERROR:        "The previous SQL caused a database error. Fix the query.",
        VALIDATOR_FAIL:  "The previous SQL failed validation. Review the rules and fix.",
    }
    base = hints.get(err.code, f"Previous attempt failed: {err.code}")
    return f"-- RETRY REASON: {base}\n-- Previous SQL error: {err.message[:200]}"
