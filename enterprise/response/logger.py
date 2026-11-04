"""Session Logger — writes structured audit records to CSV and JSONL."""
from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from pipeline.models import PipelineResponse


class SessionLogger:
    def __init__(self, results_dir: str = "results"):
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_path = self.results_dir / f"session_{ts}.csv"
        self.jsonl_path = self.results_dir / f"session_{ts}.jsonl"
        self._init_csv()

    def _init_csv(self) -> None:
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "question", "metric", "source", "attempts",
                    "row_count", "elapsed_ms", "success", "sql"
                ])

    def log(self, response: PipelineResponse) -> None:
        ts = datetime.now().isoformat()

        # Log CSV rows
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for ar in response.agent_responses:
                writer.writerow([
                    ts,
                    response.question,
                    ar.metric_name,
                    ar.sql.source,
                    ar.sql.attempts,
                    ar.result.row_count,
                    ar.result.elapsed_ms,
                    ar.result.success,
                    ar.sql.sql.replace("\n", " "),
                ])

        # Log JSONL record
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(response.model_dump_json() + "\n")

    def close(self) -> None:
        pass

    def __enter__(self) -> "SessionLogger":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def path(self) -> str:
        return str(self.csv_path)

