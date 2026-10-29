"""Fiscal / date parsing.

Zscaler FY: Aug 1 – Jul 31; FY label = calendar year the FY ends.
Supports:
  - Explicit:  Q1FY26 | Q1 FY2026 | FY26 Q1 | FY26 | FY 2026 | fiscal 2026 | 2026
  - Relative:  last/past/previous N quarters | last quarter | this year | YTD
  - Compared:  "Q1FY26 vs Q1FY25" / "FY25 to FY26" / "FY26 and FY27"

Returns a `Period` with the raw span and canonical DB labels so the rest
of the extractor can quote back the user's words AND the pipeline can
filter on `FY 2026` / `FY 2026 Q1`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional


def _to_full_year(yr: str) -> int:
    n = int(yr)
    return n if n >= 100 else 2000 + n


@dataclass
class Period:
    raw: str                                     # exact span the user typed
    fy_label: Optional[str] = None               # "FY 2026"
    fq_label: Optional[str] = None               # "FY 2026 Q1"
    kind: str = "explicit"                       # explicit | relative | range


# Order matters: multi-token patterns first so greedy regex grabs them.
_Q_FY   = re.compile(r"\bQ([1-4])\s*(?:of\s+)?(?:FY\s*|fiscal\s*)?(\d{2,4})\b", re.I)
_QUART  = re.compile(r"\bquarter\s*([1-4])\s*(?:of\s+)?(?:FY\s*|fiscal\s*)?(\d{2,4})\b", re.I)
_FY_Q   = re.compile(r"\b(?:FY\s*|fiscal\s*)?(\d{2,4})\s*Q([1-4])\b", re.I)   # also catches '2027 Q1'
_YEAR_QUART = re.compile(r"\b(20\d{2})\s*quarter\s*([1-4])\b", re.I)           # '2027 quarter 1'
_FY     = re.compile(r"\b(?:FY|fiscal\s+year|fiscal)\s*(\d{2,4})\b", re.I)
_YEAR   = re.compile(r"\b(20\d{2})\b")
_REL  = re.compile(
    r"\b(?:last|past|previous|prior)\s+(\d{1,2})\s+(?:quarters?|(?:fiscal\s+)?years?)\b"
    r"|\b(?:last|previous|prior|this|current|next)\s+(?:quarter|fiscal\s+year|year|fy)\b"
    r"|\bytd\b|\byear[- ]to[- ]date\b",
    re.I,
)
_SPLIT_RE = re.compile(r"\s*(?:vs\.?|versus|and|to|through|-|–|,)\s*", re.I)


def _match_single(text: str) -> Optional[Period]:
    """Parse a single period token (no 'vs')."""
    for pat in (_Q_FY, _QUART):
        if m := pat.search(text):
            q, yr = int(m.group(1)), _to_full_year(m.group(2))
            return Period(m.group(0), f"FY {yr}", f"FY {yr} Q{q}")
    for pat in (_FY_Q, _YEAR_QUART):
        if m := pat.search(text):
            yr, q = _to_full_year(m.group(1)), int(m.group(2))
            return Period(m.group(0), f"FY {yr}", f"FY {yr} Q{q}")
    if m := _FY.search(text):
        yr = _to_full_year(m.group(1))
        return Period(m.group(0), f"FY {yr}")
    if m := _YEAR.search(text):
        yr = int(m.group(1))
        return Period(m.group(0), f"FY {yr}")
    if m := _REL.search(text):
        return Period(m.group(0), kind="relative")
    return None


def parse(text: str) -> list[Period]:
    """Find every fiscal span in `text`, in order. One per comparison side.

    'Q1FY26 vs Q1FY25' -> [Q1FY26, Q1FY25].  A trailing standalone year
    inside a longer span is swallowed (so "FY 2026" is not two periods).
    """
    out: list[Period] = []
    taken: list[tuple[int, int]] = []
    for pat in (_FY_Q, _YEAR_QUART, _Q_FY, _QUART, _FY, _REL, _YEAR):
        for m in pat.finditer(text):
            if any(a <= m.start() and m.end() <= b for a, b in taken):
                continue
            p = _match_single(m.group(0))
            if p:
                out.append(p)
                taken.append(m.span())
    # Sort by position in the text so group-splitting sees them in order.
    out.sort(key=lambda p: text.lower().find(p.raw.lower()))
    return out
