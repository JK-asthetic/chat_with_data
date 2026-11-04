"""Intent + operator + limit from cue words. Deterministic.

Priority order (first-match-wins): RISK > TREND > COMPARE > DELTA > RANK > LOOKUP > AGGREGATE.
"""
from __future__ import annotations

import re
from typing import Optional

_TOP      = re.compile(r"\btop\b|\bhighest\b|\bbiggest\b|\blargest\b|\bbest\b", re.I)
_BOTTOM   = re.compile(r"\bbottom\b|\blowest\b|\bsmallest\b|\bworst\b|\bleast\b", re.I)
_LIMIT    = re.compile(r"\b(?:top|bottom)\s+(\d+)\b", re.I)
_SINGULAR = re.compile(
    r"\b(?:top|bottom|biggest|largest|highest|smallest|lowest)\s+"
    r"(?:single\s+|one\s+)?(?:account|company|customer)\b"
    r"|\bwhich\s+(?:account|company|customer)\s+(?:has|is|have)\b", re.I)

_CUES = {
    "RISK":    re.compile(r"\brisk|\bchurn|downsell|non[- ]?renew|contraction|contracting"
                          r"|\bshrink|\bdeclin|\breduc|\bdecreas|\bdrop(?:ped)?\b|\blost\b|cancel", re.I),
    "TREND":   re.compile(r"\btrend|\btrajectory|over time|\bby (?:quarter|month|year)\b"
                          r"|quarterly|monthly|histor|quarter[- ]by[- ]quarter"
                          r"|\b(?:last|past) \d+ (?:quarters|months|(?:fiscal )?years)\b", re.I),
    "COMPARE": re.compile(r"\bcompar|\bversus\b|\bvs\.?(?=\s|$)|\bagainst\b|\bbetween\b.+\band\b", re.I),
    "DELTA":   re.compile(r"\bgrow|\bgrowth|\bchang|\bincreas|\bdelta|\bgain|\bexpan"
                          r"|\bincremental|new[- ]logo|net[- ]new|\bqoq\b|\byoy\b", re.I),
}

_METRIC_CUES = (
    # NACV before NNACV before ACV — longest match wins
    ("NACV",     re.compile(r"\bnacv\b(?!\s*excl|\s*net)|nacv[- ]target|new[- ]acv[- ]target|new acv target", re.I)),
    ("NNACV",    re.compile(r"\bnnacv\b|net[- ]new[- ]acv|new[- ]acv(?!\s*target)|nnacv[- ]target", re.I)),
    ("ACV",      re.compile(r"\bacv\b|annual contract value|booking value|bookings", re.I)),
    ("INCR_ARR", re.compile(r"incr(?:emental)?[ _]?arr|net[- ]new arr|new arr|\binc[- ]arr\b", re.I)),
    ("CHURN",    re.compile(r"downsell|\bchurn\b|churned|contraction|lost arr", re.I)),
    ("QTY",      re.compile(r"\bqty\b|quantity|seats?\b|licenses?\b|units?\b", re.I)),
)


def infer(text: str, *, has_account: bool, is_multi_group: bool) -> str:
    for name in ("RISK", "TREND"):
        if _CUES[name].search(text):
            return name
    if is_multi_group or _CUES["COMPARE"].search(text):
        return "COMPARE"
    if _CUES["DELTA"].search(text):
        return "DELTA"
    if _TOP.search(text) or _BOTTOM.search(text):
        return "RANK"
    return "LOOKUP" if has_account else "AGGREGATE"


def operator(text: str) -> Optional[str]:
    if _TOP.search(text):
        return "top"
    if _BOTTOM.search(text):
        return "bottom"
    return None


def limit(text: str, op: Optional[str]) -> Optional[int]:
    if m := _LIMIT.search(text):
        return max(1, min(100, int(m.group(1))))
    if op and _SINGULAR.search(text):
        return 1
    return None


def metric(text: str) -> str:
    for name, rx in _METRIC_CUES:
        if rx.search(text):
            return name
    return "ARR"
