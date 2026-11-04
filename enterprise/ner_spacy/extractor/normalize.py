"""Text normalisation before matching.

The NLP stack (spaCy tagger, PhraseMatcher) is sensitive to quirky input:
smart quotes, unicode spaces, "Quaters" instead of "quarters". Fix once,
up front, so every downstream module sees clean text. We only touch
whitespace / punctuation / known typos — never real content.
"""
from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz, process


# Common misspellings observed in production prompts.
_TYPO_MAP = {
    r"\b(quaters?|quarers?|qurters?|qrtrs?|qtrs?)\b": "quarters",
    r"\bqtr\b": "quarter",
    r"\bFY\s*-\s*(\d{2,4})\b": r"FY\1",         # "FY - 26" -> "FY26"
    r"\bQ\s*-\s*([1-4])\b": r"Q\1",             # "Q - 1" -> "Q1"
}

# Smart quotes / dashes -> ascii.
_UNICODE_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", "​": "",
})


_NUM_WORDS = {w: str(i) for i, w in enumerate(
    "one two three four five six seven eight nine ten eleven twelve".split(), 1)}
_REL_CUE = r"(?:last|past|previous|prior)"
_NUM_WORD_RE = re.compile(rf"\b({_REL_CUE})\s+({'|'.join(_NUM_WORDS)})\b", re.I)
_REL_UNIT_RE = re.compile(rf"\b({_REL_CUE}\s+\d{{1,2}})\s+([A-Za-z]+)\b", re.I)
_UNITS = ("quarters", "quarter", "years", "year")


def _relative_period(text: str) -> str:
    """'last three quester' -> 'last 3 quarter', 'past 2 yaers' -> 'past 2 years'.

    Only the words right after a last/past/previous/prior cue are touched, so 'one' or 'year' elsewhere
    (company names, 'ARR by year') are left alone. The unit is fuzzy-matched; 'accounts', 'fiscal', 'months'
    score too low against quarter/year and pass through unchanged."""
    text = _NUM_WORD_RE.sub(lambda m: f"{m.group(1)} {_NUM_WORDS[m.group(2).lower()]}", text)

    def fix_unit(m: re.Match) -> str:
        word = m.group(2).lower()
        if word not in _UNITS:
            best = process.extractOne(word, _UNITS, scorer=fuzz.ratio, score_cutoff=70)
            if not best:
                return m.group(0)
            word = best[0]
        if not m.group(1).split()[-1] == "1" and not word.endswith("s"):
            word += "s"                                  # 'last 3 quarter' -> 'last 3 quarters'
        return f"{m.group(1)} {word}"

    return _REL_UNIT_RE.sub(fix_unit, text)


def normalize(text: str) -> str:
    """Deterministic normalisation. Idempotent."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_UNICODE_MAP)
    for pat, repl in _TYPO_MAP.items():
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return _relative_period(text)
