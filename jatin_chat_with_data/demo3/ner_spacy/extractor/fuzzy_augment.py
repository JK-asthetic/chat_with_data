"""Length-aware fuzzy matching for closed-set labels.

The PhraseMatcher in `matchers.py` is exact. This module runs AFTER it on
the still-unlabeled tokens and tries to catch typos:
    "EMAE"      → EMEA
    "Americsa"  → AMERICAS  → Americas
    "enterprize"→ ENTERPRISE → Enterprise
    "ZPAN"      → ZPA
    "Digital Experince" → DIGITAL EXPERIENCE (bigram pass)

Strategy — threshold depends on length because `fuzz.ratio` is cruel to
short strings:
    * length ≤ 4   → require Damerau-Levenshtein distance ≤ 1
                     (catches EMAE → EMEA transposition as 1 edit)
    * length 5-7   → require score ≥ 85
    * length ≥ 8   → require score ≥ 82

Only PROPN / NOUN / ADJ tokens are considered. Stop words, verbs, numbers,
metric words, and tokens already covered by exact or earlier hits are
skipped so we never promote "ARR" or "for" into a GEO.

Bigram pass: adjacent uncovered token pairs are also tried against
multi-word aliases (aliases that contain a space). This catches typos in
the second word of a compound product name, e.g. "Digital Experince".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from rapidfuzz import fuzz, process
from rapidfuzz.distance import DamerauLevenshtein
from spacy.tokens import Doc, Token

from .matchers import Hit


_SKIP_LEMMAS = {"arr", "acv", "churn", "revenue", "growth", "trend",
                "quarter", "year", "fy", "ytd", "total", "all", "company",
                "account", "customer", "client", "who", "what", "how",
                "which", "when", "where"}


@dataclass
class _AliasBank:
    """Pre-processed per-label alias table for fuzzy lookup."""
    label: str
    alias_to_canon: dict[str, str]           # UPPER alias -> canonical DB value
    short_aliases:  list[str]                # len <= 4, no space (Levenshtein path)
    long_aliases:   list[str]                # len >= 5, no space (ratio path)
    multi_aliases:  list[str] = field(default_factory=list)  # aliases with a space (bigram path)

    @classmethod
    def build(cls, label: str, aliases: dict[str, str]) -> "_AliasBank":
        upper = {k.upper(): v for k, v in aliases.items()}
        short = [a for a in upper if len(a) <= 4 and " " not in a]
        long  = [a for a in upper if len(a) >= 5 and " " not in a]
        multi = [a for a in upper if " " in a]
        return cls(label, upper, short, long, multi)


class FuzzyClosedSetMatcher:
    """Finds typo'd closed-set entities missed by the PhraseMatcher."""

    def __init__(self, geo: dict[str, str], product: dict[str, str], segment: dict[str, str]):
        self._banks = [
            _AliasBank.build("GEO", geo),
            _AliasBank.build("PRODUCT", product),
            _AliasBank.build("SEGMENT", segment),
        ]

    def find(self, doc: Doc, already_hit: Iterable[tuple[int, int]]) -> list[Hit]:
        covered: set[int] = set()
        for a, b in already_hit:
            for tok in doc:
                if a <= tok.idx and tok.idx + len(tok.text) <= b:
                    covered.add(tok.i)

        out: list[Hit] = []

        # ── single-token pass ────────────────────────────────────────────────
        for tok in doc:
            if tok.i in covered or not self._candidate(tok):
                continue
            cand = tok.text.upper()
            best: tuple[str, str, float] | None = None   # (label, canonical, score)
            for bank in self._banks:
                hit = self._try_bank(cand, bank)
                if hit and (best is None or hit[2] > best[2]):
                    best = hit
            if best:
                label, canon, score = best
                out.append(Hit(label, canon, tok.text, tok.idx, tok.idx + len(tok.text)))
                covered.add(tok.i)

        # ── bigram pass — catches typos in multi-word aliases ────────────────
        # e.g. "Digital Experince" → "DIGITAL EXPERIENCE"
        for i in range(len(doc) - 1):
            t1, t2 = doc[i], doc[i + 1]
            if t1.i in covered or t2.i in covered:
                continue
            if not self._candidate(t1) or not self._candidate_soft(t2):
                continue
            bigram = f"{t1.text.upper()} {t2.text.upper()}"
            for bank in self._banks:
                hit = self._try_multi(bigram, bank)
                if hit:
                    label, canon, score = hit
                    out.append(Hit(label, canon, f"{t1.text} {t2.text}",
                                  t1.idx, t2.idx + len(t2.text)))
                    covered.add(t1.i)
                    covered.add(t2.i)
                    break

        return out

    @staticmethod
    def _candidate(tok: Token) -> bool:
        if tok.pos_ not in ("PROPN", "NOUN", "ADJ"):
            return False
        if tok.is_stop or tok.is_punct or tok.like_num:
            return False
        if len(tok.text) < 3:
            return False
        if tok.lemma_.lower() in _SKIP_LEMMAS:
            return False
        return True

    @staticmethod
    def _candidate_soft(tok: Token) -> bool:
        """Looser check for the second token in a bigram — allow X/PROPN/NOUN/ADJ."""
        if tok.pos_ not in ("PROPN", "NOUN", "ADJ", "X"):
            return False
        if tok.is_stop or tok.is_punct or tok.like_num:
            return False
        if len(tok.text) < 2:
            return False
        return True

    @staticmethod
    def _try_bank(cand: str, bank: _AliasBank) -> tuple[str, str, float] | None:
        """Return (label, canonical, score 0..1) if a fuzzy match clears."""
        # Short path — require edit distance <= 1 against similarly short aliases
        if len(cand) <= 4 and bank.short_aliases:
            best_alias, best_dist = None, 99
            for a in bank.short_aliases:
                if abs(len(a) - len(cand)) > 1:
                    continue
                d = DamerauLevenshtein.distance(cand, a)
                if d < best_dist:
                    best_alias, best_dist = a, d
            if best_alias is not None and 1 <= best_dist <= 1:
                return (bank.label, bank.alias_to_canon[best_alias], 0.9)
            return None
        # Long path — ratio threshold scaled by length
        pool = bank.long_aliases if len(cand) >= 5 else bank.long_aliases + bank.short_aliases
        if not pool:
            return None
        res = process.extractOne(cand, pool, scorer=fuzz.ratio)
        if not res:
            return None
        alias, score, _idx = res
        cutoff = 82 if len(cand) >= 8 else 85
        if abs(len(alias) - len(cand)) > 2:       # a typo is a couple of characters off, not a longer name
            return None
        if score >= cutoff and alias.upper() != cand:
            return (bank.label, bank.alias_to_canon[alias], score / 100.0)
        return None

    @staticmethod
    def _try_multi(cand: str, bank: _AliasBank) -> tuple[str, str, float] | None:
        """Fuzzy match a bigram candidate against multi-word aliases (aliases with spaces)."""
        if not bank.multi_aliases:
            return None
        res = process.extractOne(cand, bank.multi_aliases, scorer=fuzz.ratio)
        if not res:
            return None
        alias, score, _idx = res
        # Allow a few chars of slack but not a completely different length
        if abs(len(alias) - len(cand)) > 3:
            return None
        if score >= 85:
            return (bank.label, bank.alias_to_canon[alias], score / 100.0)
        return None
