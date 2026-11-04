"""
Session memory — stores resolved entities and result rows per turn.

In-process implementation.  Redis-ready: replace the _store dict with
redis.get/set calls keyed by user_id:session_id for production.

Design: Never stores raw chat text.  Follow-ups are resolved from actual
result rows, never from LLM guessing.

Usage::

    mem = SessionMemory()
    mem.add(Turn(query="top 5 accounts", standalone="top 5 accounts",
                 entities={}, columns=["account_name","arr"],
                 rows=[{"account_name":"Acme","arr":1_000_000}]))
    text, notes, unresolved = mem.resolve_references("what about the second one?")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TURNS = 6
"""Maximum number of turns kept in memory per session."""

MAX_ROWS = 10
"""Maximum number of result rows stored per turn (to cap memory footprint)."""

ACCOUNT_COLS: tuple[str, ...] = (
    "end_user_name",
    "account_name",
    "end_user_parent_name",
    "customer",
    "company",
)
"""Column names (case-insensitive match) considered to hold account display names."""

_ORDINALS: dict[str, int] = {
    "first": 0,  "1st": 0,
    "second": 1, "2nd": 1,
    "third": 2,  "3rd": 2,
    "fourth": 3, "4th": 3,
    "fifth": 4,  "5th": 4,
    "sixth": 5,  "6th": 5,
    "seventh": 6,"7th": 6,
    "eighth": 7, "8th": 7,
    "ninth": 8,  "9th": 8,
    "tenth": 9,  "10th": 9,
    "last": -1,
}
"""Word-to-index mapping for positional references ("the second one")."""

# Pronoun/reference patterns that signal a follow-up
_REFERENCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(it|its|they|them|their|that|those|this|these)\b", re.I),
    re.compile(r"\b(the\s+(?:same|above|previous|prior|following|mentioned))\b", re.I),
    re.compile(r"\b(him|her|his)\b", re.I),
]

_ORDINAL_RE = re.compile(
    r"\bthe\s+(" + "|".join(re.escape(k) for k in _ORDINALS) + r")\s+(?:one|account|company|customer)?\b",
    re.I,
)
"""Pattern that matches ordinal references like 'the second one' or 'the 3rd account'."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def account_column(columns: list[str]) -> str | None:
    """Return the first column in *columns* that looks like an account name column.

    Comparison is case-insensitive.

    Args:
        columns: List of column names from a query result set.

    Returns:
        The matching column name (original case) or ``None`` if not found.
    """
    lower_map = {c.lower(): c for c in columns}
    for candidate in ACCOUNT_COLS:
        if candidate in lower_map:
            return lower_map[candidate]
    return None


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    """One completed conversation turn stored in session memory.

    Attributes:
        query:      The raw question the user asked.
        standalone: The standalone (follow-up rewritten) version, or same as query.
        entities:   Serialised resolved-entity snapshot for context injection.
        columns:    Column names from the query result.
        rows:       Up to MAX_ROWS rows from the query result (dicts of col→value).
    """

    query: str
    standalone: str
    entities: dict[str, Any]    = field(default_factory=dict)
    columns: list[str]          = field(default_factory=list)
    rows: list[dict[str, Any]]  = field(default_factory=list)

    def __post_init__(self) -> None:
        # Trim rows to cap memory usage
        if len(self.rows) > MAX_ROWS:
            self.rows = self.rows[:MAX_ROWS]


@dataclass
class SessionMemory:
    """In-process session memory with follow-up reference resolution.

    Thread-safety: not guaranteed for concurrent writes.  For production
    multi-user deployments, replace ``_turns`` with a Redis-backed list.

    Attributes:
        _turns: Ordered list of :class:`Turn` objects, newest last.
    """

    _turns: list[Turn] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, turn: Turn) -> None:
        """Append *turn* and evict the oldest if memory exceeds MAX_TURNS.

        Args:
            turn: The completed turn to store.
        """
        self._turns.append(turn)
        if len(self._turns) > MAX_TURNS:
            self._turns = self._turns[-MAX_TURNS:]

    def clear(self) -> None:
        """Wipe all stored turns (e.g. on session logout or explicit /reset)."""
        self._turns.clear()

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def last_accounts(self) -> list[str]:
        """Return the account names from the most recent turn's result rows.

        Uses :func:`account_column` to locate the right column.

        Returns:
            Ordered list of account name strings, empty list if none.
        """
        if not self._turns:
            return []
        last = self._turns[-1]
        col = account_column(last.columns)
        if col is None:
            return []
        return [str(row[col]) for row in last.rows if col in row]

    def prompt_context(self, n: int = 3) -> list[dict[str, Any]]:
        """Build a compact context list for injection into the LLM classifier prompt.

        Each dict has keys: ``turn``, ``query``, ``accounts``, ``columns``.

        Args:
            n: Maximum number of recent turns to include.

        Returns:
            List of context dicts, ordered oldest-first.
        """
        recent = self._turns[-n:] if len(self._turns) >= n else self._turns[:]
        result: list[dict[str, Any]] = []
        for i, t in enumerate(recent):
            col = account_column(t.columns)
            accounts = [str(r[col]) for r in t.rows if col and col in r][:5]
            result.append(
                {
                    "turn": i + 1,
                    "query": t.standalone or t.query,
                    "accounts": accounts,
                    "columns": t.columns,
                }
            )
        return result

    def allowed_text(self) -> str:
        """Return a compact text summary of what the user may refer to.

        Used to tell the LLM classifier what reference targets exist.

        Returns:
            Multi-line string enumerating recent result accounts.
        """
        lines: list[str] = []
        for i, t in enumerate(self._turns[-3:], start=1):
            col = account_column(t.columns)
            names = [str(r[col]) for r in t.rows if col and col in r][:5]
            if names:
                lines.append(f"Turn {i} accounts: {', '.join(names)}")
        return "\n".join(lines) if lines else "(no prior results)"

    # ------------------------------------------------------------------
    # Reference resolution
    # ------------------------------------------------------------------

    def resolve_references(
        self,
        text: str,
    ) -> tuple[str, list[str], list[str]]:
        """Rewrite *text* by substituting follow-up references with explicit values.

        Resolution strategy (in order):
        1. Ordinal references ("the second one") → account name from last result.
        2. Pronoun references ("it", "they", …) → inject last account list.
        3. If no reference found, return unchanged.

        Args:
            text: The raw user question.

        Returns:
            A three-tuple of:
            - ``rewritten``: Text with references replaced.
            - ``notes``:     Human-readable explanation of what was substituted.
            - ``unresolved``: Reference phrases that could not be resolved.
        """
        rewritten  = text
        notes:      list[str] = []
        unresolved: list[str] = []

        if not self._turns:
            return rewritten, notes, unresolved

        last = self._turns[-1]
        last_accounts = self.last_accounts()

        # -- 1. Ordinal references ------------------------------------------
        def _replace_ordinal(m: re.Match[str]) -> str:
            word = m.group(1).lower()
            idx  = _ORDINALS.get(word, None)
            if idx is None:
                unresolved.append(m.group(0))
                return m.group(0)
            try:
                account = last_accounts[idx]
            except IndexError:
                unresolved.append(m.group(0))
                return m.group(0)
            notes.append(f"'{m.group(0)}' → '{account}'")
            return account

        rewritten = _ORDINAL_RE.sub(_replace_ordinal, rewritten)

        # -- 2. Pronoun / generic reference detection -----------------------
        has_reference = any(p.search(rewritten) for p in _REFERENCE_PATTERNS)
        if has_reference and last_accounts:
            account_list = ", ".join(last_accounts[:5])
            # Build an addendum rather than rewriting pronouns directly
            # (rewriting "it" can break grammar; addendum is safer)
            addendum = f" (referring to: {account_list})"
            rewritten = rewritten.rstrip() + addendum
            notes.append(f"Pronoun resolved to prior results: {account_list}")
        elif has_reference and not last_accounts:
            # We detected a pronoun but have nothing to resolve it to
            for pat in _REFERENCE_PATTERNS:
                for match in pat.finditer(rewritten):
                    unresolved.append(match.group(0))

        return rewritten, notes, unresolved

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:  # pragma: no cover
        return len(self._turns)

    def __bool__(self) -> bool:  # pragma: no cover
        return bool(self._turns)
