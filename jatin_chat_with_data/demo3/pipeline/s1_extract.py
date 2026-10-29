"""
Stage 1 — Rule-based entity + intent extractor (no model).

Produces a small, flat raw JSON — only what the user said.
No account IDs, no table names, no schema knowledge.
Enrichment happens in S2 (parallel tools).

Every field comes from a dedicated, testable method:
  - period     regex over Q1FY26 / FY26 / "last 4 quarters" / YTD (typos in 'quarters' tolerated)
  - region     schema.yaml geo aliases, word-bounded (a country word inside a company name does not count)
  - segment    schema.yaml segment aliases, longest match first
  - products   schema.yaml aliases + the product hierarchy loaded from data_arr
  - company    capitalised phrases confirmed against dim_account (verbs and region/product words excluded)
  - intent     cue priority (RISK > TREND > COMPARE > DELTA > RANK > LOOKUP > AGGREGATE)
  - operator / limit_n / metric   cue words
`_ground` is the single cleaning pass and still drops anything not traceable to the query text.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from core import companies, hierarchy
from core.config import get_schema
from pipeline.models import ExtractedQuery, Intent

# ── Fiscal period ─────────────────────────────────────────────────────────────

_Q_FIRST_RE = re.compile(r"\bQ([1-4])\s*(?:FY\s*|fiscal\s*)?(\d{2,4})\b", re.IGNORECASE)
# A year needs an explicit FY/fiscal prefix or four digits, so 'top 10' is never read as FY 2010.
_FISCAL_RE  = re.compile(
    r"(?:\b(?:FY|fiscal\s+year|fiscal)\s*(\d{2,4})\b|\b(20\d{2})\b)"
    r"(?:[\s\-\/]?(?:Q|quarter\s*)([1-4]))?",
    re.IGNORECASE,
)

def _to_full_year(yr: str) -> str:
    return f"20{yr}" if len(yr) == 2 else yr

def _normalize_fiscal(text: str) -> tuple[Optional[str], Optional[str]]:
    """Returns (fiscal_year_label, fiscal_quarter_label) in DB format."""
    m = _Q_FIRST_RE.search(text)
    if m:
        q, yr = m.group(1), _to_full_year(m.group(2))
        fy = f"FY {yr}"
        return fy, f"{fy} Q{q}"
    m = _FISCAL_RE.search(text)
    if m:
        yr = _to_full_year(m.group(1) or m.group(2))
        fy = f"FY {yr}"
        q  = m.group(3)
        return fy, f"{fy} Q{q}" if q else None
    return None, None


_QTR_TYPO = re.compile(r"\b(?:quaters?|quarers?|qurters?|qrtrs?|qtrs?|qtr)\b", re.I)


def _fix_typos(query: str) -> str:
    """'last 4 Quaters' -> 'last 4 quarters': the period parsers only know the correct spelling."""
    return _QTR_TYPO.sub(lambda m: "quarters" if m.group(0).lower().endswith("s") else "quarter", query)


_FISCAL_TOKEN = re.compile(
    r"\bQ[1-4]\s*(?:of\s+)?(?:FY|fiscal)?\s*\d{2,4}\b"      # Q1FY26, Q1 FY 2026, q1 2027
    r"|\bFY\s*\d{2,4}\s*Q[1-4]\b"                             # FY26 Q1
    r"|\b(?:FY|fiscal\s+year|fiscal)\s*\d{2,4}\b", re.I)      # FY26, fiscal 2026
_FISCAL_REL = re.compile(
    r"\b(?:last|past|previous|prior)\s+\d{1,2}\s+quarters?\b"
    r"|\b(?:last|previous|prior|this|current)\s+(?:quarter|fiscal\s+year|year|fy)\b"
    r"|\bytd\b|\byear[- ]to[- ]date\b", re.I)


def _find_fiscal(query: str) -> Optional[str]:
    """The period exactly as typed. Two explicit periods ('Q1FY26 ... vs Q1FY25') are joined with ' vs '."""
    seen: list[str] = []
    spans = []
    for m in _FISCAL_TOKEN.finditer(query):
        tok = " ".join(m.group(0).split())
        if tok.lower() not in (t.lower() for t in seen):
            seen.append(tok)
            spans.append(m.span())
    if len(seen) >= 2 and re.fullmatch(r"\s*(?:to|vs\.?|versus|and|through|-|–|,)\s*", query[spans[0][1]:spans[1][0]], re.I):
        return " ".join(query[spans[0][0]:spans[1][1]].split())      # 'FY25 to FY26' exactly as typed
    if seen:
        return " vs ".join(seen)
    m = _FISCAL_REL.search(query)
    return m.group(0) if m else None


# ── Off-topic guard ───────────────────────────────────────────────────────────
# Queries with none of these signals are not analytics questions and are blocked
# before S2/LLM so "hi", "thanks", etc. never hit the DB.
_ANALYTICS_SIGNAL = re.compile(
    r"\barr\b|\bacv\b|\bchurn\b|\brevenue\b|\bgrowth\b|\btop\b|\bbottom\b"
    r"|\btrend\b|\bquarter\b|\bfiscal\b|\bfy\d\d\b|\bq[1-4]\b"
    r"|\baccount\b|\baccounts\b|\bcustomer\b|\bcompan(?:y|ies)\b"
    r"|\bproduct\b|\bgeo\b|\bregion\b|\bsegment\b|\bemea\b|\bapj\b|\bamer\b|\bapac\b"
    r"|\bdownsell\b|\bupsell\b|\brenewal\b|\bmetric\b|\busage\b|\bquantity\b|\bqty\b"
    r"|\brank\b|\bbreakdown\b|\bsplit\b|\bcompare\b|\bversus\b|\bvs\b|\bdelta\b",
    re.I,
)

# Key analytics terms for typo-tolerant fallback (only tokens >= 5 chars checked).
_ANALYTICS_KEYWORDS = frozenset([
    "revenue", "quarter", "fiscal", "account", "accounts", "product", "growth",
    "segment", "metric", "trend", "churn", "renewal", "upsell", "downsell",
    "quantity", "usage", "breakdown", "compare", "versus", "delta", "customer",
])


def _has_analytics_signal(query: str) -> bool:
    """True if the query contains an analytics signal word, even with minor typos."""
    if _ANALYTICS_SIGNAL.search(query):
        return True
    # Fuzzy fallback: any word >= 5 chars close to a key analytics term?
    import difflib
    tokens = re.findall(r"\b\w{5,}\b", query.lower())
    for tok in tokens:
        if difflib.get_close_matches(tok, _ANALYTICS_KEYWORDS, n=1, cutoff=0.82):
            return True
    return False

# ── Cue words: operator, limit, intent, metric ────────────────────────────────

_TOP_RE    = re.compile(r"\btop\b|\bhighest\b|\bmost\b|\bbiggest\b|\blargest\b|\bbest\b|\bwho\s+has\b", re.I)
_BOTTOM_RE = re.compile(r"\bbottom\b|\blowest\b|\bleast\b|\bsmallest\b|\bworst\b", re.I)
_LIMIT_RE  = re.compile(r"\b(?:top|bottom)\s+(\d+)\b", re.I)
# 'the top account' / 'biggest customer' (singular) asks for ONE row; plural 'top accounts' keeps the default.
_SINGULAR_RE = re.compile(
    r"\b(?:top|bottom|biggest|largest|highest|smallest|lowest|best|worst)\s+(?:single\s+|one\s+)?"
    r"(?:account|company|customer)\b"
    r"|\bwhich\s+(?:account|company|customer)\s+(?:has|is|have)\b", re.I)

_INTENT_CUES = {
    "TREND": re.compile(
        r"\btrend|\btrajectory|over time|\bby (?:quarter|month|year)\b|\bper (?:quarter|month)\b|quarterly|monthly"
        r"|\b(?:each|every) (?:quarter|month)\b|histor|\b(?:last|past) \d+ (?:quarters|months)\b"
        r"|across (?:the )?(?:last|past|quarters)|quarter[- ]by[- ]quarter", re.I),
    "COMPARE": re.compile(r"\bcompar|\bversus\b|\bagainst\b|\bbetween\b.+\band\b|\bdifference\b", re.I),
    "VS": re.compile(r"\bvs\.?(?=\s|$)", re.I),          # 'A vs B' is a comparison unless a growth/change word is present
    # an account losing ARR: downsell, churn, decline, reduction, contraction (curated labels treat these as RISK)
    "RISK": re.compile(r"\brisk\b|\bchurn|\bcancel|non[- ]?renew|downsell|contraction|contracting|\bshrink"
                       r"|\bdeclin|\breduc|\bdecreas|\bdrop(?:ped)?\b|\blost\b", re.I),
    "DELTA": re.compile(
        r"\bgrow|\bgrowth|\bchang|\bincreas|\bdelta|\bgain|\bexpan|\bincremental|\bmov(?:e|ed|ement)\b"
        r"|\bdiffer|new[- ]logo|net[- ]new|\bnew arr\b|\bqoq\b|\byoy\b|(?:quarter|year)[- ]over[- ](?:quarter|year)"
        r"|\b(?:went|goes?|going|gone|moved?|trending)\s+(?:up|down)\b|\b(?:up|down)\s+(?:by\s+)?\d", re.I),
}

# A multi-quarter window means one row per quarter; summing quarterly ARR snapshots would double-count.
_MULTI_QUARTER_RE = re.compile(r"\b(?:last|past|previous|prior)\s+(?:[2-9]|\d{2})\s+quarters\b", re.I)

_METRICS = ("ARR", "INCR_ARR", "ACV", "CHURN")
_METRIC_CUES = (
    ("ACV", re.compile(r"\bacv\b", re.I)),
    ("INCR_ARR", re.compile(r"incr(?:emental)?[ _]?arr|net[- ]new arr|new arr", re.I)),
    ("CHURN", re.compile(r"downsell|\bchurn", re.I)),
)


def _infer_intent(query: str, account: Optional[str], operator: Optional[str], fiscal: Optional[str] = None) -> str:
    """Cue priority: RISK > TREND > COMPARE > DELTA > 'A vs B' > two periods > RANK > LOOKUP > AGGREGATE."""
    if _INTENT_CUES["RISK"].search(query):
        return "RISK"
    if _INTENT_CUES["TREND"].search(query) or (not operator and _MULTI_QUARTER_RE.search(query)):
        return "TREND"
    if _INTENT_CUES["COMPARE"].search(query):
        return "COMPARE"
    if _INTENT_CUES["DELTA"].search(query):
        return "DELTA"
    if _INTENT_CUES["VS"].search(query) or (fiscal and re.search(r" (?:vs|and) ", fiscal)):
        return "COMPARE"
    if operator and not account:
        return "RANK"
    return "LOOKUP" if account else "AGGREGATE"


# ── Region and segment finders ────────────────────────────────────────────────

_SKIP_SEGMENT_ALIASES = {"STATE", "GLOBAL", "STRATEGIC", "ENT", "COMM", "FED", "MM", "LE"}  # common words / ambiguous


def _typed_spans(query: str, keys: list[str]) -> list[str]:
    """Each key as typed in the query, longest key first; a key inside a longer match does not count again."""
    taken: list[tuple[int, int]] = []
    out: list[str] = []
    for key in sorted(keys, key=len, reverse=True):
        short = len(key) <= 2
        for m in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])", query, 0 if short else re.I):
            if any(a <= m.start() and m.end() <= b for a, b in taken):
                continue
            taken.append(m.span())
            out.append(m.group(0))
    return out


def _find_geo(query: str, aliases: dict) -> list[str]:
    return _typed_spans(query, list(aliases))


def _find_segments(query: str, schema: dict) -> list[str]:
    return _typed_spans(query, [k for k in schema.get("segment_aliases", {}) if k not in _SKIP_SEGMENT_ALIASES])


def _rule_raw(query: str) -> dict:
    """Candidates found by rules, in the shape `_ground` cleans (products and company are recalled there)."""
    schema = get_schema()
    return {
        "intent": None, "account_raw": None, "products_raw": [],
        "geo_raw": _find_geo(query, schema.get("geo_aliases", {})),
        "segment_raw": _find_segments(query, schema),
        "metric_raw": "ARR", "fiscal_raw": _find_fiscal(query),
    }


LOG_GUARD_DROPS = False   # print what the guard trimmed (candidates a rule found that the query does not support)

# ── Grounding guard ───────────────────────────────────────────────────────────

_FISCAL_CUE_RE = re.compile(
    r"q[1-4]|fy\s?\d|fiscal|quarter|\b20\d{2}\b|\b(?:ytd|h[12])\b|year[- ]to[- ]date"
    r"|\b(?:last|this|next|prior|previous|current)\s+(?:year|fy)\b",
    re.I,
)

def _span(query: str, phrase: str) -> Optional[str]:
    """Return `phrase` as typed in `query` (word-bounded), else None.

    Phrases of <=2 chars (US, NA, UK, LE, PS) must match as typed in capitals,
    so common words like 'us' never count as a region or product.
    """
    short = len(phrase) <= 2
    p = phrase.upper() if short else phrase
    m = re.search(rf"(?<![A-Za-z0-9]){re.escape(p)}(?![A-Za-z0-9])", query, 0 if short else re.I)
    return m.group(0) if m else None


def _ground_products(items: list[str], query: str) -> list[str]:
    """Keep a product only if the user typed it (aliases and hierarchy names are added by recall)."""
    out: list[str] = []
    for p in (str(i).strip() for i in items):
        if p and p not in out and _span(query, p):
            out.append(p)
    return out


_GENERIC_PRODUCT_ALIASES = {"PLATFORM", "BUNDLE", "BUNDLES", "PS"}


def _recall_products(found: list[str], query: str, aliases: dict) -> list[str]:
    """Add products the model missed that the query names via an unambiguous alias."""
    covered = {aliases.get(p.upper(), p.upper()) for p in found}
    out = list(found)
    for key, canon in aliases.items():
        if key in _GENERIC_PRODUCT_ALIASES or canon in covered:
            continue
        if typed := _span(query, key):
            out.append(typed)
            covered.add(canon)
    return out


def _recall_hierarchy(found: list[str], query: str) -> list[str]:
    """Add product-hierarchy names typed in the query (levels 1-3, plus multi-word deeper names)."""
    have = {p.lower() for p in found}
    out = list(found)
    for name in sorted(set(hierarchy.matchable_names()), key=len, reverse=True):
        if len(name) < 3 or name.upper() in _GENERIC_PRODUCT_ALIASES or name.lower() in have:
            continue
        if _span(query, name):
            out.append(name)
            have.add(name.lower())
    return out


def _drop_nested(products: list[str], query: str) -> list[str]:
    """Drop a product whose every mention sits inside a longer product's mention ('SWG' in 'Core SWG')."""
    def spans(p: str) -> list[tuple[int, int]]:
        return [m.span() for m in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(p)}(?![A-Za-z0-9])", query, re.I)]

    by_product = {p: spans(p) for p in products}
    keep = []
    for p, mine in by_product.items():
        outer = [s for q, qs in by_product.items() if len(q) > len(p) for s in qs]
        if mine and all(any(o0 <= s0 and s1 <= o1 for o0, o1 in outer) for s0, s1 in mine):
            continue
        keep.append(p)
    return keep


def _ground_geo(items: list[str], query: str, aliases: dict) -> list[str]:
    """Keep a region only if the query evidences it (abbreviation, region or country word).

    This also rules out fiscal strings and segment words, which are never geo aliases.
    """
    evidenced = {canon for key, canon in aliases.items() if _span(query, key)}
    out: list[str] = []
    for g in (str(i).strip() for i in items):
        if g and g not in out and aliases.get(g.upper()) in evidenced:
            out.append(g)
    return out


def _ground_segments(items: list[str], query: str, schema: dict) -> list[str]:
    """Keep only known segments. Restore the full alias the user typed when the model
    truncated it (model says 'enterprise', user typed 'large enterprise')."""
    aliases = schema.get("segment_aliases", {})
    out: list[str] = []
    for s in (str(i).strip() for i in items):
        longer = [t for k in aliases if s and s.upper() in k and (t := _span(query, k))]
        typed = max(longer, key=len) if longer else None
        if s.upper() in aliases and s in _typed_spans(query, [k for k in aliases if s.upper() in k]):
            typed = s  # typed as its own alias ('enterprise' next to 'large enterprise'): do not widen it
        if typed and typed not in out:
            out.append(typed)
    return out


_QUERY_WORDS = {
    "arr", "acv", "churn", "downsell", "total", "trend", "compare", "show", "give", "tell", "what", "which",
    "who", "how", "much", "many", "list", "get", "find", "breakdown", "average", "sum", "revenue", "growth",
    "quarter", "year", "last", "this", "next", "previous", "current", "ytd", "products", "product", "is",
    "are", "does", "do", "us", "me", "we", "our", "my", "all", "any", "overall", "please", "can", "could",
    # imperative verbs that open a request ("Take the top 20 ...") and happen to exist as account names
    "take", "pull", "fetch", "rank", "calculate", "run", "return", "provide", "check", "report", "plot",
    "display", "summarize", "summarise", "highlight", "identify", "name", "produce", "generate", "break",
    "zscaler",   # the platform owner is never a customer
    # greetings / fillers that open a message
    "hi", "hey", "hello", "quick", "need", "as", "also", "thanks", "thank", "context", "before", "following",
    "i", "i'm", "i've", "i'd", "i'll", "we", "we're", "it", "its", "let", "one", "a", "an", "the",
    # function words are never a company, even typed in capitals ("... account IN EMEA")
    "in", "on", "at", "for", "of", "by", "to", "from", "with", "without", "and", "or", "vs", "versus", "than",
    "across", "over", "under", "between", "during", "within", "about", "per", "if", "so", "but", "then", "when",
}
# Generic business words: never a company ON THEIR OWN ("Net ARR change"), still fine inside a name ("New Relic").
# Plain-word deep products — never a company name
_PLAIN_DEEP_PRODUCTS = {"bandwidth", "breach", "breakout", "dedicated", "extranet", "promo", "zenith"}

_GENERIC_SINGLE = {"major", "majors", "sase", "sse", "platform", "security", "network", "cloud", "data", "identity", "endpoint",
                   "workload", "browser", "branch", "net", "new", "gross", "quarterly", "monthly", "annual", "yearly", "average", "latest", "recent",
                   "worldwide", "incremental", "expected", "forecast", "base", "lost", "churned", "declining", "growing", "rising",
                   "falling", "expanding", "global", "south", "north", "east",
                   "west", "latin", "middle", "central", "southeast", "northern", "southern"} | _PLAIN_DEEP_PRODUCTS
_LEGAL_SUFFIX = {"inc", "ltd", "corp", "co", "plc", "sa", "s.a", "ag", "llc", "llp", "gmbh", "nv", "bv", "ab", "as",
                 "se", "spa", "pty", "pte"}
# 'Take the top 20 ...' / 'Show me ...': a capitalised first word followed by a determiner is a verb, not a company.
_LEADING_VERB_RE = re.compile(r"^\s*\S+\s+(?:the|a|an|me|us|all|my|our|any|each|every|those|these|only|just)\b", re.I)
_NAME_CONNECTORS = {"of", "and", "&", "the", "de", "von", "van"}
_FISCAL_TOKEN_RE = re.compile(r"q[1-4](?:fy)?\d{0,4}|fy\d{2,4}|20\d{2}", re.I)


def _is_known_product(p: str, aliases: dict) -> bool:
    return bool(hierarchy.find(p) or p.upper() in aliases)


# ── Companies ─────────────────────────────────────────────────────────────────
# A capitalised run of words is a company when it sits where a company goes:
#   strong  'ARR for X', 'ARR of X', 'does X have', '— X', "X's ARR", 'X ARR' (not as the first word), and any X
#           chained to an accepted one by ',' / 'and' / 'or' / 'vs'  -> accepted even if the account list does not
#           know it, so S2 can say "company not found" instead of the question silently going global
#   weak    anything else -> accepted only if the account list confirms it: a lone word must BE an account name
#           ('Hello', 'Quick', 'Sarah' are not), a longer phrase may be the start of one
# A lowercase name ('royal bank of canada') is found by trying n-grams at strong positions or next to a metric
# word, confirmed by the account list.
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9&.'’\-]*|&")
_RUN_CONNECTORS = {"of", "de", "von", "van", "&"}
_STRONG_PREV = {"for", "of", "at", "from"}
_NOUN_PREV = {"account", "company", "customer", "client"}      # 'the account Cisco', 'the customer Shell'
_ON_PREV = {"on"}                                               # 'Quick one on Bank of America Corp: ...'
_AFTER_WINDOW = 8
_ASK_PREV = {"does", "did"}
_STRONG_NEXT = {"arr", "acv", "churn", "downsell", "growth", "trend", "revenue", "total", "have", "has", "had"}
_CHAIN = {"and", "or", "vs", "vs.", "versus", ","}
_METRIC_TOKENS = {"arr", "acv", "churn", "downsell", "growth", "trend", "revenue", "spend", "renewal", "decline",
                  "history", "position", "change"}
_STOP_NGRAM = {"the", "a", "an", "all", "each", "every", "any", "our", "my", "this", "that", "those", "these", "it",
               "its", "their", "them", "top", "bottom", "last", "next", "current", "total", "whole", "entire", "only"}


def _core(tok: str) -> str:
    """Token without a possessive or trailing full stop: "Toyota's" -> "Toyota", "Mastercard." -> "Mastercard"."""
    return re.sub(r"(?:'s|’s)$", "", tok).rstrip(".")


def _name_words(schema: dict) -> tuple[set[str], set[str], set[str]]:
    """(words that can never be part of a company, whole phrases that are never a company, single geo words)."""
    blocked = set(_QUERY_WORDS) | _GENERIC_ACCOUNT_WORDS
    for key in ("product_aliases", "segment_aliases"):
        for alias in schema.get(key, {}):
            blocked |= set(alias.lower().split())
    for name in hierarchy.names():
        blocked |= set(name.lower().split())
    reserved = {a.lower() for k in ("product_aliases", "segment_aliases", "geo_aliases") for a in schema.get(k, {})}
    geo_words = {a.lower() for a in schema.get("geo_aliases", {}) if " " not in a}
    return blocked, reserved, geo_words


def _runs(query: str, blocked: set[str], geo_words: set[str]) -> list[dict]:
    """Capitalised runs of words with their position and neighbours."""
    toks = list(_TOKEN_RE.finditer(query))

    def namey(tok: re.Match) -> bool:
        c = _core(tok.group())
        return bool(c) and (c[0].isupper() or c[0].isdigit()) and any(ch.isalpha() for ch in c) \
            and c.lower() not in blocked and not _FISCAL_TOKEN_RE.fullmatch(c)

    out: list[dict] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if not namey(t) or _core(t.group()).lower() in _RUN_CONNECTORS:
            i += 1
            continue
        j = i
        while j + 1 < len(toks):
            last = toks[j].group()
            if last.endswith((".", "'s", "’s")) and _core(last).lower() not in _LEGAL_SUFFIX:
                break                                           # sentence end or possessive ends the name
            nxt = toks[j + 1]
            nc = _core(nxt.group()).lower()
            if query[toks[j].end():nxt.start()].strip():        # punctuation (',', ';', '—') ends a run
                break
            if nc in _RUN_CONNECTORS and j + 2 < len(toks) and namey(toks[j + 2]) \
                    and not query[nxt.end():toks[j + 2].start()].strip():
                j += 2
                continue
            if namey(nxt) and nc not in geo_words and nc not in _RUN_CONNECTORS:
                j += 1
                continue
            break
        end_tok = toks[j].group()
        phrase = query[t.start():toks[j].end()]
        phrase = re.sub(r"(?:'s|’s)$", "", phrase)
        if not (end_tok.endswith(".") and _core(end_tok).lower() in _LEGAL_SUFFIX and len(phrase.split()) > 1):
            phrase = phrase.rstrip(".")                         # keep the dot of 'Inc.' / 'Ltd.', drop a sentence end
        prev = _core(toks[i - 1].group()).lower() if i else ""
        out.append({"phrase": phrase, "start": t.start(), "end": toks[j].end(), "prev": prev,
                    "next": _core(toks[j + 1].group()).lower() if j + 1 < len(toks) else "",
                    "first": i == 0, "poss": end_tok.lower().endswith(("'s", "’s")),
                    "metric_before": any(_core(x.group()).lower() in _METRIC_TOKENS for x in toks[max(0, i - 6):i]),
                    "metric_after": any(_core(x.group()).lower() in _METRIC_TOKENS
                                        for x in toks[j + 1:j + 1 + _AFTER_WINDOW]),
                    "next_is_word": j + 1 < len(toks) and (_core(toks[j + 1].group()).lower() in blocked
                                                           or bool(_FISCAL_TOKEN_RE.fullmatch(_core(toks[j + 1].group())))),
                    "between": query[toks[i - 1].end():t.start()] if i else ""})
        i = j + 1
    return out


def _find_accounts(query: str, schema: dict, known_products: list[str]) -> list[str]:
    """Every company named in the question, in order of appearance."""
    for p in known_products:  # a product phrase ('Core SWG') is never a company
        query = re.sub(re.escape(p), " | ", query, flags=re.I)
    blocked, reserved, geo_words = _name_words(schema)
    lead = query.strip().split(" ", 1)[0] if _LEADING_VERB_RE.match(query) else None
    runs = [r for r in _runs(query, blocked, geo_words)
            if r["phrase"].lower() not in reserved and r["phrase"] != lead
            and not (" " not in r["phrase"] and (r["phrase"].lower() in geo_words
                                                  or r["phrase"].lower() in _GENERIC_SINGLE))]

    def strong(r: dict) -> bool:
        return ((r["prev"] in _STRONG_PREV and (r["metric_before"] or r["metric_after"]))
                or (r["prev"] in _ON_PREV and r["metric_after"] and not r["metric_before"])
                or r["prev"] in _ASK_PREV or r["prev"] in _NOUN_PREV
                or r["between"].strip() in {"—", "–", "-"} or r["poss"]
                or (r["next"] in _STRONG_NEXT and not r["first"])
                or (r["first"] and r["next_is_word"] and r["next"] not in _GENERIC_SINGLE))   # 'PayPal DLP ARR', 'Toyota ARR'

    single_weak = sorted({r["phrase"] for r in runs if not strong(r) and " " not in r["phrase"]
                          and not (r["first"] and r["next"] in _STRONG_NEXT)})
    other_weak = sorted({r["phrase"] for r in runs if not strong(r) and r["phrase"] not in single_weak})
    hits = companies.existing(single_weak, exact=True) | companies.existing(other_weak)
    found: list[dict] = []
    for r in runs:
        accept = strong(r) or r["phrase"].lower() in hits
        if not accept and found and r["between"].strip().lower() in _CHAIN and found[-1]["end"] <= r["start"]:
            accept = True          # 'Toyota and BMW', 'Siemens or Toyota': chained to an accepted company
        if accept:
            found.append(r)
    names = [r["phrase"] for r in found]
    if not names:
        names = _lowercase_accounts(query, blocked, reserved)
    return sorted({n: None for n in names if not any(n != m and n in m for m in names)}, key=query.lower().find)


def _lowercase_accounts(query: str, blocked: set[str], reserved: set[str]) -> list[str]:
    """Names typed in lowercase: n-grams right after 'for/of/at/from/does' or right before a metric word,
    confirmed by the account list (a lone word must BE an account name)."""
    toks = list(_TOKEN_RE.finditer(query))
    low = [_core(t.group()).lower() for t in toks]
    cands: list[tuple[int, str]] = []
    for i in range(len(toks)):
        starts = []
        if low[i] in _STRONG_PREV | _ASK_PREV | _ON_PREV | _NOUN_PREV and i + 1 < len(toks):
            before = any(x in _METRIC_TOKENS for x in low[max(0, i - 6):i])
            after = any(x in _METRIC_TOKENS for x in low[i + 1:i + 1 + _AFTER_WINDOW + 3])
            if low[i] in _ASK_PREV | _NOUN_PREV or before or after:
                starts.append(i + 1)
        if low[i] in _STRONG_NEXT - {"total", "have", "has", "had"} and i > 0:
            starts += [max(0, i - n) for n in (1, 2, 3)]               # 'microsoft arr', 'bank of america arr'
        for st in starts:
            for size in (4, 3, 2, 1):
                w = [_core(x.group()) for x in toks[st:st + size]]
                if len(w) < size or {x.lower() for x in (w[0], w[-1])} & (_STOP_NGRAM | blocked) \
                        or any(_FISCAL_TOKEN_RE.fullmatch(x) or x.lower() in _STRONG_NEXT for x in w) \
                        or any(query[toks[st + k].end():toks[st + k + 1].start()].strip() for k in range(size - 1)):
                    continue
                phrase = " ".join(w)
                if phrase.lower() not in reserved and (size > 1 or len(phrase) >= 3):
                    cands.append((st, phrase))
    hits = companies.existing(sorted({p for _, p in cands if p.lower() not in _GENERIC_SINGLE}))
    confirmed = [(st, p) for st, p in cands if p.lower() in hits and (" " in p or len(p) >= 4)]
    out: list[str] = []
    for st, p in sorted(confirmed, key=lambda x: (x[0], -len(x[1]))):
        if not any(p in o or o in p for o in out):
            out.append(p)
    return out[:3]


def _recall_accounts(query: str, schema: dict, known_products: list[str]) -> list[str]:
    return _find_accounts(query, schema, known_products)


def _recall_account(query: str, schema: dict, known_products: list[str]) -> Optional[str]:
    """First company named in the question, or None."""
    found = _recall_accounts(query, schema, known_products)
    return found[0] if found else None


def _rescue_account(items: list[str], query: str, schema: dict) -> Optional[str]:
    """The model sometimes files a company name under segment_raw; recover a typed proper noun."""
    for s in items:
        words = re.findall(r"[a-z0-9/]+", s.lower())
        if s[:1].isupper() and not any(w in _GENERIC_ACCOUNT_WORDS for w in words) \
                and s.upper() not in schema.get("segment_aliases", {}):
            if acct := _ground_account(s, query, schema):
                return acct
    return None


_GENERIC_ACCOUNT_WORDS = {
    "top", "bottom", "highest", "lowest", "most", "least", "biggest", "largest", "smallest", "best", "worst",
    "all", "every", "each", "the", "our", "my", "companies", "company", "customers", "customer",
    "accounts", "account", "clients", "client", "null", "none", "n/a",
}


def _ground_account(acct: object, query: str, schema: dict) -> Optional[str]:
    if not isinstance(acct, str):
        return None
    a = acct.strip()
    if not a or not _span(query, a):
        return None
    if all(w in _GENERIC_ACCOUNT_WORDS for w in re.findall(r"[a-z0-9/]+", a.lower())):
        return None
    reserved = ("product_aliases", "segment_aliases", "geo_aliases")
    if any(a.upper() in schema.get(k, {}) for k in reserved):
        return None
    return a


def _ground(raw: dict, query: str) -> dict:
    """Drop every extracted value that is not traceable to the query text."""
    schema = get_schema()
    product_aliases = schema.get("product_aliases", {})
    segment_items = [str(i).strip() for i in raw.get("segment_raw") or []]
    # a segment word ('enterprise') is not a product, even if a hierarchy node shares its name
    product_query = query
    for seg in _ground_segments(segment_items, query, schema):
        product_query = re.sub(rf"(?<![A-Za-z0-9]){re.escape(seg)}(?![A-Za-z0-9])", " ", product_query, flags=re.I)
    products = _drop_nested(
        _recall_hierarchy(
            _recall_products(_ground_products(raw.get("products_raw") or [], product_query), product_query,
                             product_aliases),
            product_query),
        product_query)
    account = _ground_account(raw.get("account_raw"), query, schema)
    rescued = False
    if not account and (account := _rescue_account(segment_items, query, schema)):
        rescued = True
    if not account and (account := _recall_account(
            query, schema, [p for p in products if _is_known_product(p, product_aliases)])):
        # the model sometimes files a company name under products_raw
        products = [p for p in products if p.lower() != account.lower()]
    # A country word inside a company name ('Indian Oil') is not evidence of a region.
    geo_query = query.replace(account, " ") if account else query
    cleaned = {
        "account_raw": account,
        "products_raw": products,
        "geo_raw": _ground_geo(raw.get("geo_raw") or [], geo_query, schema.get("geo_aliases", {})),
        "segment_raw": _ground_segments(segment_items, query, schema),
    }

    dropped = {
        k: [v for v in (raw.get(k) or [])
            if not any(str(v).strip().lower() in c.lower() for c in cleaned[k])]
        for k in ("products_raw", "geo_raw", "segment_raw")
    }
    if rescued:
        dropped["segment_raw"] = [s for s in dropped.get("segment_raw", []) if s != account]
        print(f"    ↳ S1 guard moved {account!r} from segment_raw to account_raw")
    if raw.get("account_raw") and not cleaned["account_raw"]:
        dropped["account_raw"] = [raw["account_raw"]]
    dropped = {k: v for k, v in dropped.items() if v}
    if dropped and LOG_GUARD_DROPS:
        print(f"    ↳ S1 guard dropped: {json.dumps(dropped)}")

    fiscal = raw.get("fiscal_raw")
    fiscal = fiscal.strip() if isinstance(fiscal, str) else None
    # A real period has a digit or a relative word; a bare 'quarter' (as in 'by quarter') is not one.
    has_period = bool(fiscal and re.search(r"\d|\b(?:last|this|next|prior|previous|current|ytd|year[- ]to[- ]date)\b", fiscal, re.I))
    cleaned["fiscal_raw"] = fiscal if has_period and _FISCAL_CUE_RE.search(query) else None

    # operator / limit are derived from the query text, never from the model
    operator = "top" if _TOP_RE.search(query) else ("bottom" if _BOTTOM_RE.search(query) else None)
    m_limit = _LIMIT_RE.search(query)
    cleaned["operator"] = operator
    cleaned["limit_n"] = int(m_limit.group(1)) if m_limit else (1 if operator and _SINGULAR_RE.search(query) else None)
    # no other invented default; S4 decides

    supplied = raw.get("intent") in {i.value for i in Intent}
    intent = raw["intent"] if supplied else _infer_intent(query, cleaned["account_raw"], operator, cleaned["fiscal_raw"])
    # An intent handed in from outside must be backed by a cue word in the query.
    if supplied and intent in _INTENT_CUES and not _INTENT_CUES[intent].search(query):
        intent = "AGGREGATE"
    if intent == "LOOKUP" and not cleaned["account_raw"]:
        intent = "AGGREGATE"
    if intent == "AGGREGATE" and rescued:
        intent = "LOOKUP"  # the model missed that a company was named
    if intent == "AGGREGATE" and not operator and _MULTI_QUARTER_RE.search(query):
        intent = "TREND"
    if intent == "AGGREGATE" and operator:
        intent = "RANK"
    cleaned["intent"] = intent

    metric = raw.get("metric_raw") if raw.get("metric_raw") in _METRICS else "ARR"
    if metric == "ARR":  # an explicit metric word beats a default
        metric = next((name for name, rx in _METRIC_CUES if rx.search(query)), "ARR")
    cleaned["metric_raw"] = metric
    # Off-topic guard: block greetings and non-analytics text before hitting S2/LLM.
    if not _has_analytics_signal(query):
        cleaned["missing_critical"] = ["not_arr_query"]
    else:
        cleaned["missing_critical"] = []
    return cleaned


# ── Public entry points ───────────────────────────────────────────────────────

def find_slots(query: str) -> dict:
    """What is typed in `query`, by the same rules as extract(): used by S0 to split and to share scope."""
    text = _fix_typos(query)
    schema = get_schema()
    cleaned = _ground(_rule_raw(text), text)
    known = [p for p in cleaned["products_raw"] if _is_known_product(p, schema.get("product_aliases", {}))]
    return {
        "accounts": _recall_accounts(text, schema, known),
        "products": cleaned["products_raw"], "geo": cleaned["geo_raw"],
        "segments": cleaned["segment_raw"], "fiscal": cleaned["fiscal_raw"],
    }


def extract(query: str) -> ExtractedQuery:
    """S1: rule-based extraction -> grounding guard -> fiscal regex normalisation. No model call."""
    text = _fix_typos(query)
    raw = _ground(_rule_raw(text), text)

    limit = max(1, min(int(raw["limit_n"]), 100)) if raw["limit_n"] else None

    # Fiscal labels in DB format, for display and S2
    fiscal_year, fiscal_quarter = _normalize_fiscal(text)

    return ExtractedQuery(
        raw_query        = query,
        intent           = Intent(raw["intent"]),
        metric_raw       = raw["metric_raw"],
        account_raw      = raw["account_raw"],
        products_raw     = raw["products_raw"],
        geo_raw          = raw["geo_raw"],
        segment_raw      = raw["segment_raw"],
        fiscal_raw       = raw["fiscal_raw"],
        fiscal_year      = fiscal_year,
        fiscal_quarter   = fiscal_quarter,
        operator         = raw["operator"],
        limit_n          = limit,
        missing_critical = raw["missing_critical"],
    )
