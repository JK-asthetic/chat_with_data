"""Split a comparison query into entity groups.

"Compare ARR for companies in EMEA in 2026 vs companies in AMER in 2027"
                                         ^^^^
                                    split here

Rules:
  - Split only on COMPARISON cues ('vs', 'versus', 'compared to') and on
    'and' when it joins two parallel-looking clauses (both sides contain
    at least one entity hit). Otherwise 'and' is a list connector.
  - Each side keeps its own fiscal / geo / segment / account filters.
  - Products / segments that only appear once are treated as SHARED and
    copied into every group (handled by the caller).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


_HARD_SPLIT = re.compile(r"\s+(?:vs\.?|versus|compared\s+to|against)\s+", re.I)
_SOFT_SPLIT = re.compile(r"\s+and\s+(?=\S)", re.I)
# A soft 'and' split only counts as a comparison when the sentence announces
# one explicitly. Without a cue, 'A and B' is a list ("Private Access and
# Digital Experience ARR" is one query about two products, not two queries).
_COMPARE_CUE = re.compile(r"\b(?:compare|comparison|compared|between)\b", re.I)


@dataclass
class Side:
    text:  str
    start: int
    end:   int


def _apply(text: str, pat: re.Pattern) -> list[Side]:
    sides: list[Side] = []
    last = 0
    for m in pat.finditer(text):
        sides.append(Side(text[last:m.start()], last, m.start()))
        last = m.end()
    sides.append(Side(text[last:], last, len(text)))
    return sides


def split(text: str, hits_per_side_check) -> list[Side]:
    """Return 1+ sides. `hits_per_side_check(side_text) -> int` counts
    entity hits in a candidate split; used to decide if an 'and' is really
    a comparison or just a list connector.
    """
    # 1) Hard split on explicit comparison cues
    sides = _apply(text, _HARD_SPLIT)
    if len(sides) > 1:
        return [s for s in sides if s.text.strip()]

    # 2) Try soft split on 'and' — but ONLY when the sentence has an
    #    explicit comparison cue ('Compare A and B', 'between X and Y').
    #    Otherwise 'and' is a list connector: "Private Access and Digital
    #    Experience ARR" is one query about two products.
    if _COMPARE_CUE.search(text):
        candidate = _apply(text, _SOFT_SPLIT)
        if len(candidate) >= 2:
            counts = [hits_per_side_check(s.text) for s in candidate]
            if all(c >= 1 for c in counts) and sum(counts) >= 3:
                return [s for s in candidate if s.text.strip()]

    return [Side(text, 0, len(text))]
