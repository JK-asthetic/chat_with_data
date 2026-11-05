"""Zscaler fiscal calendar (Aug 1 - Jul 31): quarter bounds, last month of a quarter, month parsing.

Q1 = Aug-Oct, Q2 = Nov-Jan, Q3 = Feb-Apr, Q4 = May-Jul; FY is named after the year it ends in
(FY 2027 = Aug 2026 .. Jul 2027). data_arr keeps one snapshot per quarter, labelled with the quarter's
LAST month ('FY 2027 Q1 OCT'); data_quantity is monthly (fiscal_month = first day of the month).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
Quarter = tuple[int, int]  # (fiscal year, quarter 1-4)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def quarter_of(d: date) -> Quarter:
    return (d.year + 1, (d.month - 8) // 3 + 1) if d.month >= 8 else (d.year, (d.month + 4) // 3 + 1)


def parse_quarter(label: str) -> Optional[Quarter]:
    m = re.fullmatch(r"FY (\d{4}) Q([1-4])", (label or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def label(q: Quarter) -> str:
    return f"FY {q[0]} Q{q[1]}"


def prev_quarter(q: Quarter) -> Quarter:
    return (q[0], q[1] - 1) if q[1] > 1 else (q[0] - 1, 4)


def next_quarter(q: Quarter) -> Quarter:
    return (q[0], q[1] + 1) if q[1] < 4 else (q[0] + 1, 1)


def last_complete_quarter(today: Optional[date] = None) -> Quarter:
    """The latest quarter that has fully ended (the quarter before the one containing `today`)."""
    return prev_quarter(quarter_of(today or date.today()))


def trailing(q: Quarter, n: int) -> list[Quarter]:
    """`n` quarters ending at `q` (inclusive), oldest first."""
    out = [q]
    for _ in range(n - 1):
        out.insert(0, prev_quarter(out[0]))
    return out


def quarters_of_year(fy: int) -> list[Quarter]:
    return [(fy, 1), (fy, 2), (fy, 3), (fy, 4)]


def quarter_start(q: Quarter) -> date:
    return add_months(date(q[0] - 1, 8, 1), 3 * (q[1] - 1))


def quarter_end(q: Quarter) -> date:
    return add_months(quarter_start(q), 3) - timedelta(days=1)


def last_month_start(q: Quarter) -> date:
    """First day of the quarter's last month — data_quantity.fiscal_month for the quarter-end snapshot."""
    return add_months(quarter_start(q), 2)


def arr_month_label(q: Quarter) -> str:
    """data_arr.fiscal_month value of the quarter's snapshot, e.g. 'FY 2027 Q1 OCT'."""
    return f"{label(q)} {_ABBR[quarter_end(q).month - 1]}"


def clamp_range(quarters: list[str], last_closed: Optional[Quarter]) -> list[str]:
    """A relative range ('last 4 quarters') must end at the latest closed quarter. Drop later quarters and
    prepend earlier ones so the count is kept."""
    keys = [parse_quarter(q) for q in quarters]
    if not last_closed or len(quarters) < 2 or any(k is None for k in keys):
        return quarters
    kept = [k for k in keys if k <= last_closed]
    dropped = len(keys) - len(kept)
    if not dropped or not kept:
        return quarters
    for _ in range(dropped):
        kept.insert(0, prev_quarter(kept[0]))
    return [label(k) for k in kept]


def month_end(month_start: date) -> date:
    return add_months(month_start, 1) - timedelta(days=1)


_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_WITH_YEAR = re.compile(rf"\b{_MON}\.?,?\s+(?:of\s+)?(20\d{{2}})\b", re.I)
_WITH_FY = re.compile(rf"\b{_MON}\.?\s+(?:of\s+)?(?:in\s+)?FY\s?'?(\d{{2,4}})\b", re.I)
_SHORT_YEAR = re.compile(rf"\b{_MON}[-’']\s?(\d{{2}})\b", re.I)
_BARE = re.compile(rf"\b(?:in|for|of|during|as of|at|by|since|until|through|from)\s+{_MON}\b(?!\s+\d)", re.I)


def find_month(text: str, today: Optional[date] = None) -> Optional[date]:
    """First day of a month mentioned in `text` ('October 2026', 'Oct FY27', "Oct'26", 'in September'), else None."""
    if not text:
        return None
    today = today or date.today()

    def ok(tok: str) -> bool:
        return tok.lower() != "may" or tok == "May"      # the verb 'may' is not a month

    for rx in (_WITH_YEAR, _WITH_FY, _SHORT_YEAR):
        for m in rx.finditer(text):
            if not ok(m.group(1)):
                continue
            mon, yr = _MONTHS[m.group(1).lower()], int(m.group(2))
            if rx is _WITH_FY:
                fy = 2000 + yr if yr < 100 else yr
                return date(fy - 1 if mon >= 8 else fy, mon, 1)
            return date(2000 + yr if yr < 100 else yr, mon, 1)
    for m in _BARE.finditer(text):
        if not ok(m.group(1)):
            continue
        mon = _MONTHS[m.group(1).lower()]
        d = date(today.year, mon, 1)
        return d if d <= today.replace(day=1) else date(today.year - 1, mon, 1)
    return None
