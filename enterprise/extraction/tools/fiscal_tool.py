"""Fiscal Tool — parses and normalizes fiscal periods.

Handles:
  - Single quarter: 'Q1FY26', 'FY 2026 Q1', 'FY26 Q1'
  - Year: 'FY 2026', 'FY26', 'fiscal 2026'
  - Ranges & comparisons: 'Q1FY26 vs Q3FY26', 'FY25 to FY26'
  - Relative periods: 'last quarter', 'this quarter', 'last 4 quarters', 'YTD'
"""
from __future__ import annotations

import asyncio
from datetime import date
import re
from typing import Optional

from pipeline.models import Fiscal, Intent
from core.db import query_one
from core.settings import get_db

_Q_FIRST_RE = re.compile(r"Q([1-4])\s*(?:FY\s*|fiscal\s*)?(\d{2,4})", re.IGNORECASE)
_FY_RE = re.compile(r"(?:FY\s*|fiscal\s+year\s*)?(\d{2,4})(?:[\s\-\/]?Q([1-4]))?", re.IGNORECASE)
_REL_N_RE = re.compile(r"\b(?:last|past|previous|prior)\s+(\d{1,2})\s+(quarters?|(?:fiscal\s+)?years?)\b", re.IGNORECASE)
_REL_Q_RE = re.compile(r"\b(?:last|previous|prior)\s+quarter\b", re.IGNORECASE)
_CUR_Q_RE = re.compile(r"\b(?:this|current)\s+quarter\b", re.IGNORECASE)
_YTD_RE = re.compile(r"\bytd\b|\byear[- ]to[- ]date\b", re.IGNORECASE)
_REL_Y_RE = re.compile(r"\b(?:last|previous|prior)\s+(?:fiscal\s+)?year\b|\blast\s+fy\b", re.IGNORECASE)
_CUR_Y_RE = re.compile(r"\b(?:this|current)\s+(?:fiscal\s+)?year\b|\bcurrent\s+fy\b", re.IGNORECASE)


def quarter_of(d: date) -> tuple[str, str]:
    """Zscaler fiscal calendar: Aug 1 - Jul 31.

    Q1: Aug-Oct, Q2: Nov-Jan, Q3: Feb-Apr, Q4: May-Jul.
    """
    month = d.month
    year = d.year
    if month >= 8:
        fy = year + 1
        q = (month - 8) // 3 + 1
    else:
        fy = year
        q = (month + 4) // 3 + 1
    return f"FY {fy}", f"FY {fy} Q{q}"


def trailing_quarters(end_q: str, n: int) -> list[str]:
    """Returns list of n quarters ending at end_q (inclusive)."""
    parts = end_q.split()  # ["FY", "2026", "Q1"]
    fy = int(parts[1])
    q = int(parts[2][1])
    quarters = []
    for _ in range(n):
        quarters.append(f"FY {fy} Q{q}")
        q -= 1
        if q == 0:
            q = 4
            fy -= 1
    return list(reversed(quarters))


def _parse_fiscal_raw(fiscal_raw: Optional[str]) -> Fiscal:
    if not fiscal_raw:
        return Fiscal()

    def _full(yr: str) -> str:
        return f"20{yr}" if len(yr) == 2 else yr

    all_q = [(int(m.group(1)), _full(m.group(2))) for m in _Q_FIRST_RE.finditer(fiscal_raw)]
    distinct_q = list(dict.fromkeys(all_q))
    if len(distinct_q) >= 2:
        labels = [f"FY {yr} Q{q}" for q, yr in distinct_q]
        return Fiscal(quarter_labels=labels, is_range=True)

    if len(distinct_q) == 1:
        q, yr = distinct_q[0]
        fy_label = f"FY {yr}"
        fq_label = f"{fy_label} Q{q}"
        return Fiscal(fy=int(yr), quarter=q, is_range=False,
                      fiscal_quarter_label=fq_label, fiscal_year_label=fy_label)

    m = _FY_RE.search(fiscal_raw)
    if m:
        yr = _full(m.group(1))
        q = int(m.group(2)) if m.group(2) else None
        fy_label = f"FY {yr}"
        fq_label = f"{fy_label} Q{q}" if q else None
        return Fiscal(fy=int(yr), quarter=q, is_range=False,
                      fiscal_quarter_label=fq_label, fiscal_year_label=fy_label)

    return Fiscal()


def _parse_relative(text: str, today: Optional[date] = None) -> Optional[Fiscal]:
    if not text:
        return None
    cur_fy, cur_fq = quarter_of(today or date.today())
    if m := _REL_N_RE.search(text):
        n = int(m.group(1)) * (4 if m.group(2).lower().endswith(("year", "years")) else 1)
        labels = trailing_quarters(cur_fq, max(1, min(n, 20)))
        return Fiscal(quarter_labels=labels, is_range=len(labels) > 1)
    if _REL_Q_RE.search(text):
        prior = trailing_quarters(cur_fq, 2)[0]
        return Fiscal(fiscal_quarter_label=prior, fiscal_year_label=prior.rsplit(" ", 1)[0])
    if _CUR_Q_RE.search(text):
        return Fiscal(fiscal_quarter_label=cur_fq, fiscal_year_label=cur_fy)
    if _YTD_RE.search(text):
        labels = [q for q in trailing_quarters(cur_fq, 4) if q.startswith(cur_fy)]
        return Fiscal(quarter_labels=labels, is_range=len(labels) > 1)
    if _REL_Y_RE.search(text):
        year = int(cur_fy.split()[1]) - 1
        return Fiscal(fy=year, fiscal_year_label=f"FY {year}")
    if _CUR_Y_RE.search(text):
        return Fiscal(fy=int(cur_fy.split()[1]), fiscal_year_label=cur_fy)
    return None


async def resolve_fiscal(
    fiscal_raw: Optional[str],
    fy_label: Optional[str] = None,
    fq_label: Optional[str] = None,
    raw_query: str = "",
) -> tuple[Fiscal, bool, Optional[str]]:
    relative = None if (fy_label or fq_label) else _parse_relative(fiscal_raw or raw_query)
    if relative and relative.quarter_labels:
        return relative, True, None

    fiscal = relative or _parse_fiscal_raw(fiscal_raw)

    if fy_label:
        fiscal.fiscal_year_label = fy_label
    if fq_label:
        fiscal.fiscal_quarter_label = fq_label

    if not fiscal.fiscal_year_label and not fiscal.fiscal_quarter_label and not fiscal.quarter_labels:
        return fiscal, True, None

    # Validation against DB (skips when in dry_run mode)
    cfg = get_db()
    if cfg.dry_run:
        return fiscal, True, None

    def _check() -> tuple[bool, Optional[str]]:
        if fiscal.fiscal_quarter_label:
            row = query_one("SELECT 1 FROM data_arr WHERE fiscal_quarter = %(fq)s LIMIT 1",
                            {"fq": fiscal.fiscal_quarter_label})
            if not row:
                return False, f"No data for fiscal_quarter='{fiscal.fiscal_quarter_label}'"
        elif fiscal.fiscal_year_label:
            row = query_one("SELECT 1 FROM data_arr WHERE fiscal_year = %(fy)s LIMIT 1",
                            {"fy": fiscal.fiscal_year_label})
            if not row:
                return False, f"No data for fiscal_year='{fiscal.fiscal_year_label}'"
        return True, None

    valid, warn = await asyncio.to_thread(_check)
    return fiscal, valid, warn

