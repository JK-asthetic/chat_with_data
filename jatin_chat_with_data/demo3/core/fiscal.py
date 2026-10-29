"""Zscaler fiscal calendar. FY label = calendar year the FY ends (July 31).

Q1 Aug-Oct | Q2 Nov-Jan | Q3 Feb-Apr | Q4 May-Jul
"""
from __future__ import annotations

from datetime import date


def quarter_of(d: date) -> tuple[str, str]:
    """Return (fy_label, fq_label) for a calendar date, e.g. ('FY 2027', 'FY 2027 Q1')."""
    m, y = d.month, d.year
    if 8 <= m <= 10:
        fy, q = y + 1, 1
    elif m >= 11:
        fy, q = y + 1, 2
    elif m == 1:
        fy, q = y, 2
    elif 2 <= m <= 4:
        fy, q = y, 3
    else:  # May, Jun, Jul
        fy, q = y, 4
    fyl = f"FY {fy}"
    return fyl, f"{fyl} Q{q}"


def trailing_quarters(end_label: str, n: int) -> list[str]:
    """The n quarters ending at `end_label` (inclusive), oldest first."""
    fy, q = int(end_label.split()[1]), int(end_label[-1])
    out: list[str] = []
    for _ in range(n):
        out.append(f"FY {fy} Q{q}")
        q -= 1
        if q == 0:
            fy, q = fy - 1, 4
    return out[::-1]
