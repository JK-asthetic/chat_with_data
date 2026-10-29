"""Session memory for follow-up questions.

Stores resolved entities and a few result rows per turn, never raw chat text, so what S0 reads
stays small however long the conversation gets. Values that fill a follow-up ("the second one")
come from stored result rows, never from an LLM.

ponytail: in-process only. Production = Redis keyed by user_id + session_id with a TTL (see
new_arch.md); the interface here is the part that carries over.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_TURNS = 6          # older turns fall off; the latest ones carry what a follow-up needs
MAX_ROWS = 10          # rows kept per turn: enough to resolve 'the third one', never a full result set
ACCOUNT_COLS = ("end_user_name", "account_name", "end_user_parent_name", "customer", "company")

_ORDINALS = {
    "first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4, "sixth": 5, "6th": 5, "seventh": 6, "7th": 6, "eighth": 7, "8th": 7,
    "ninth": 8, "9th": 8, "tenth": 9, "10th": 9, "last": -1,
}
_ORD_RE = re.compile(
    r"\b(?:the\s+)?(" + "|".join(_ORDINALS) + r")\s+(?:one|account|company|customer|result|entry)\b(?:'s)?",
    re.I,
)
_THAT_RE = re.compile(r"\b(?:that|this|the same)\s+(?:account|company|customer)\b(?:'s)?", re.I)


@dataclass
class Turn:
    query: str                       # what the user typed
    standalone: str                  # the self-contained question that actually ran
    entities: dict[str, Any]         # resolved account / products / geo / fiscal / metric / intent
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


def account_column(columns: list[str]) -> str | None:
    return next((c for c in columns if c.lower() in ACCOUNT_COLS), None)


@dataclass
class SessionMemory:
    turns: list[Turn] = field(default_factory=list)

    def add(self, turn: Turn) -> None:
        turn.rows = turn.rows[:MAX_ROWS]
        self.turns = (self.turns + [turn])[-MAX_TURNS:]

    def clear(self) -> None:
        self.turns = []

    def __bool__(self) -> bool:
        return bool(self.turns)

    def last_accounts(self) -> list[str]:
        """Account names in the most recent turn that has any, in row order."""
        for t in reversed(self.turns):
            col = account_column(t.columns)
            if col and t.rows:
                return [str(r[col]) for r in t.rows if r.get(col)]
            if t.entities.get("account"):
                return [t.entities["account"]]
        return []

    def prompt_context(self, n: int = 3) -> list[dict[str, Any]]:
        """Compact view of the last n turns for the S0 prompt (entities + a few rows, no raw chat)."""
        out = []
        for t in self.turns[-n:]:
            col = account_column(t.columns)
            out.append({
                "question": t.standalone,
                "entities": {k: v for k, v in t.entities.items() if v},
                "top_accounts": [str(r[col]) for r in t.rows[:5]] if col else [],
            })
        return out

    def allowed_text(self) -> str:
        """Everything a rewritten follow-up may legitimately quote: past questions, entities, result names."""
        parts: list[str] = []
        for t in self.turns[-3:]:
            parts.append(t.standalone)
            parts.extend(str(v) for v in t.entities.values() if v)
            col = account_column(t.columns)
            if col:
                parts.extend(str(r[col]) for r in t.rows)
        return " ".join(parts)

    def resolve_references(self, text: str) -> tuple[str, list[str], list[str]]:
        """Replace 'the second one' / 'that account' with the real name from the stored result.

        Returns (rewritten_text, notes, unresolved). Never guesses: an ordinal past the end of the list,
        or 'that account' when the last result listed several, goes to `unresolved`.
        """
        notes: list[str] = []
        unresolved: list[str] = []
        names = self.last_accounts()

        def ordinal(m: re.Match) -> str:
            idx = _ORDINALS[m.group(1).lower()]
            if not names or idx >= len(names):
                unresolved.append(f"'{m.group(0).strip()}' — the last result only had {len(names)} account(s)")
                return m.group(0)
            name = names[idx]
            notes.append(f"'{m.group(0).strip()}' -> {name} (row {idx + 1 if idx >= 0 else len(names)} of the last result)")
            return name + ("'s" if m.group(0).endswith("'s") else "")

        def that(m: re.Match) -> str:
            if len(names) != 1:
                unresolved.append(f"'{m.group(0).strip()}' — the last result had {len(names)} accounts, which one?")
                return m.group(0)
            notes.append(f"'{m.group(0).strip()}' -> {names[0]}")
            return names[0] + ("'s" if m.group(0).endswith("'s") else "")

        text = _ORD_RE.sub(ordinal, text)
        text = _THAT_RE.sub(that, text)
        return text, notes, unresolved
