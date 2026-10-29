"""Session run logger — appends every pipeline result to a CSV file.

One row per query. Opens (or creates) the CSV on first write so there is no
startup cost when logging is not needed.

Columns:
  timestamp, question, intent, account, products, geo, segment, order_type,
  fiscal, metric, operator, limit,
  sql_source, sql_attempts, sql,
  row_count, db_error, elapsed_ms,
  insight
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.models import PipelineResponse

# Results land here — one file per session (timestamp in name).
_LOG_DIR = Path(__file__).resolve().parents[1] / "results"

_COLUMNS = [
    "timestamp", "question",
    # S1 classification
    "intent", "account", "products", "geo", "segment", "order_type",
    "fiscal", "metric", "operator", "limit_n",
    # S5 SQL
    "sql_source", "sql_attempts", "sql",
    # S6 execution
    "row_count", "db_error", "elapsed_ms", "result_rows",
    # S7 insight
    "insight",
]


def _entity(resp: PipelineResponse, key: str, default: Any = "") -> str:
    """Pull from the entities dict saved on PipelineResponse."""
    val = resp.entities.get(key, default)
    if isinstance(val, list):
        return "; ".join(str(v) for v in val)
    return str(val) if val is not None else ""


class SessionLogger:
    """One instance per REPL session. Call `log(response)` after every run()."""

    def __init__(self, log_dir: Path | None = None):
        self._dir  = (log_dir or _LOG_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = self._dir / f"session_{ts}.csv"
        self._file = self._path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=_COLUMNS)
        self._writer.writeheader()
        self._file.flush()

    # ── public API ────────────────────────────────────────────────────────────
    def log(self, resp: PipelineResponse) -> None:
        """Append one row for this pipeline response."""
        ctx = resp.context
        gen = resp.generated
        res = resp.result

        # Flatten classification from entities dict (populated by _entities() in main.py)
        row = {
            "timestamp":   datetime.now().isoformat(timespec="seconds"),
            "question":    resp.question,
            # S1
            "intent":      ctx.intent.value if ctx.intent else "",
            "account":     _entity(resp, "account"),
            "products":    _entity(resp, "products"),
            "geo":         _entity(resp, "geo"),
            "segment":     _entity(resp, "segment"),
            "order_type":  _entity(resp, "order_type"),
            "fiscal":      _entity(resp, "fiscal"),
            "metric":      ctx.metric,
            "operator":    _entity(resp, "operator"),
            "limit_n":     ctx.limit,
            # S5
            "sql_source":  gen.source,
            "sql_attempts": gen.attempts,
            "sql":         gen.sql.replace("\n", " ").strip(),
            # S6
            "row_count":   res.row_count,
            "db_error":    res.db_error or "",
            "elapsed_ms":  res.elapsed_ms,
            "result_rows": json.dumps(res.rows, default=str) if res.rows else "[]",
            # S7
            "insight":     resp.insight[:500] if resp.insight else "",
        }
        self._writer.writerow(row)
        self._file.flush()       # write immediately so the file is readable mid-session

    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        self._file.close()

    # ── context manager ───────────────────────────────────────────────────────
    def __enter__(self) -> "SessionLogger":
        return self

    def __exit__(self, *_) -> None:
        self.close()
