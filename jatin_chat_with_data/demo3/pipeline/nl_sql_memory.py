"""
NL→SQL Memory — stores successful (question, SQL) pairs per session and recalls
the top-K most similar as few-shot examples injected into S5's prompt.

Storage: JSONL file at /tmp/zscaler_nl_sql_{session_id}.jsonl
Recall: simple keyword overlap (Jaccard on lowercased tokens, stopwords removed).
Later upgrade: LanceDB with embeddings when > 50 queries accumulated.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


_STOPWORDS = frozenset({
    "a", "an", "the", "of", "in", "for", "by", "and", "or", "with", "at", "to",
    "is", "are", "from", "where", "what", "how", "many", "accounts", "account",
    "arr", "fy", "q1", "q2", "q3", "q4", "total", "all", "show", "me", "get",
    "list", "give", "top", "bottom", "which",
})

_SESSION_ID = str(uuid.uuid4())[:8]   # new session = new file


@dataclass
class NLSQLEntry:
    question: str
    sql:      str
    metric:   str = "ARR"
    intent:   str = "AGGREGATE"
    ts:       float = field(default_factory=time.time)


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class NLSQLMemory:
    """Per-session NL→SQL store. Thread-safe for single-process use."""

    def __init__(self, session_id: str = _SESSION_ID, max_entries: int = 200):
        self._path = Path(f"/tmp/zscaler_nl_sql_{session_id}.jsonl")
        self._entries: list[NLSQLEntry] = []
        self._max = max_entries
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            for line in self._path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                self._entries.append(NLSQLEntry(**d))
        except Exception:
            pass

    def add(self, question: str, sql: str, metric: str = "ARR", intent: str = "AGGREGATE") -> None:
        """Store a successful NL→SQL pair."""
        entry = NLSQLEntry(question=question, sql=sql, metric=metric, intent=intent)
        self._entries.append(entry)
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max:]
        try:
            with self._path.open("a") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
        except Exception:
            pass

    def recall(self, question: str, k: int = 3) -> list[NLSQLEntry]:
        """Return top-k most similar past pairs by keyword Jaccard."""
        if not self._entries:
            return []
        q_tok = _tokens(question)
        scored = sorted(
            self._entries,
            key=lambda e: _jaccard(q_tok, _tokens(e.question)),
            reverse=True,
        )
        return [e for e in scored[:k] if _jaccard(q_tok, _tokens(e.question)) > 0.15]

    def few_shot_prompt(self, question: str, k: int = 3) -> str:
        """Format recalled entries as few-shot SQL examples for the S5 prompt."""
        entries = self.recall(question, k)
        if not entries:
            return ""
        lines = ["-- Past similar queries (use as style reference only):"]
        for e in entries:
            lines.append(f"-- Q: {e.question}")
            lines.append(e.sql.strip())
            lines.append("")
        return "\n".join(lines)


# Module-level singleton (one per process/session)
_memory: Optional[NLSQLMemory] = None


def get_memory() -> NLSQLMemory:
    global _memory
    if _memory is None:
        _memory = NLSQLMemory()
    return _memory
