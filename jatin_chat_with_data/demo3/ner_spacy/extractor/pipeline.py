"""Extractor orchestrator — the single public entrypoint.

Flow per query:
    normalize text
      -> spaCy parse (tokenize, POS, dep, lemma)
      -> closed-set hits (GEO/PRODUCT/SEGMENT via PhraseMatcher)
      -> fiscal periods (regex over normalised text)
      -> comparison split (one or many sides)
      -> for each side: assign closed-set hits + fiscal + accounts in-range
      -> intent / metric / operator / limit over the whole text
      -> ExtractionResult

The spaCy model is loaded once and cached. Rebuild the Extractor only
when `schema.yaml` or the known-companies list changes.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

# Text between two periods that signals a range (not a comparison): "Q4FY25
# to Q1FY26", "FY25 through FY26", "Q1-Q4". Hard comparison cues ('vs',
# 'versus', 'compared to') are handled upstream by comparison.split.
_LIST_CONNECTOR = re.compile(r"\s*(?:and|&|,)\s*", re.I)
_RANGE_CONNECTOR = re.compile(r"\s*(?:to|through|thru|-|–|—)\s*", re.I)

# "all segments" / "all geos" / "all products" means NO filter on that dimension, even when a narrower value is
# also named ("enterprise and all segments", "EMEA and all geos"): the broader ask wins.
_ALL_SCOPE = {
    "segments": re.compile(r"\ball\s+(?:the\s+)?(?:market\s+)?segments?\b", re.I),
    "geo":      re.compile(r"\ball\s+(?:the\s+)?(?:geos?|geographies|geographic\s+regions?|regions?)\b", re.I),
    "products": re.compile(r"\ball\s+(?:the\s+)?products?\b", re.I),
}
_ALL_EVIDENCE = {"segments": "SEGMENT", "geo": "GEO", "products": "PRODUCT"}

import spacy
from spacy.language import Language

from . import catalog, comparison, fiscal, intent as intent_mod
from .accounts import AccountFinder, AccountLookup
from .fuzzy_augment import FuzzyClosedSetMatcher
from .matchers import ClosedSetMatchers, Hit
from .normalize import normalize
from .types import EntityGroup, ExtractionResult


DEFAULT_MODEL = "en_core_web_sm"


def _matchable_hierarchy_names() -> list[str]:
    """demo3's hierarchy names (levels 1-3 + multi-word deeper); empty when run standalone or the DB is down."""
    try:
        from core import hierarchy
        return hierarchy.matchable_names()
    except Exception:
        return []


@lru_cache(maxsize=4)
def _load_nlp(model: str) -> Language:
    return spacy.load(model, exclude=["ner"])   # we never use spaCy's own NER


class Extractor:
    """Build once, call `.extract(query)` many times."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        lookup: Optional[AccountLookup] = None,
        known_companies: Optional[list[str]] = None,
        fuzzy_threshold: int = 82,
        use_db_product_catalog: bool = True,
    ):
        """`use_db_product_catalog`: pull `product_l1..l3 FROM data_arr` at
        startup and merge it into the PRODUCT matcher. Falls back to the
        embedded seed catalog when the DB is unreachable."""
        self._nlp = _load_nlp(model)
        self._catalog = catalog.load(prefer_db=use_db_product_catalog)
        deep = set(_matchable_hierarchy_names())     # level 4-5 names, so 'Advanced Sandbox' beats 'Sandbox'
        self._matchers = ClosedSetMatchers(self._nlp, extra_product_names=self._catalog.all_names() | deep)
        tables = self._matchers.alias_tables
        self._fuzzy_closed = FuzzyClosedSetMatcher(
            geo=tables["GEO"], product=tables["PRODUCT"], segment=tables["SEGMENT"])
        self._accounts = AccountFinder(lookup=lookup, known_names=known_companies,
                                       fuzzy_threshold=fuzzy_threshold)

    # ── helpers ───────────────────────────────────────────────────────────
    def _hit_count(self, text: str) -> int:
        """Count ANY entity on this side (closed-set, fiscal, or confirmed account).

        Used by comparison.split to decide whether 'A and B' is a comparison
        (both sides carry entities) or a list connector inside one group.
        """
        doc = self._nlp(text)
        n = len(self._matchers.find(doc)) + len(fiscal.parse(text))
        accts = self._accounts.find(doc, blocked_spans=[])
        return n + len(accts)

    def _group_for_range(
        self, text: str, char_start: int, char_end: int,
        hits: list[Hit], periods: list[fiscal.Period],
    ) -> tuple[EntityGroup, list[tuple[int, int]]]:
        """Build an EntityGroup from closed-set hits + periods inside the range."""
        g = EntityGroup()
        evidence: dict[str, list[str]] = {}
        blocked: list[tuple[int, int]] = []

        for h in hits:
            if not (char_start <= h.start and h.end <= char_end):
                continue
            # map onto a local offset for blocking inside the sub-doc later
            local = (h.start - char_start, h.end - char_start)
            blocked.append(local)
            bucket = {"GEO": g.geo, "PRODUCT": g.products, "SEGMENT": g.segments,
                      "ORDER_TYPE": g.order_types}[h.label]
            if h.canonical not in bucket:
                bucket.append(h.canonical)
            evidence.setdefault(h.label, []).append(h.literal)

        in_range: list[tuple[int, fiscal.Period]] = []
        for p in periods:
            pos = text.lower().find(p.raw.lower())
            if char_start <= pos < char_end:
                in_range.append((pos, p))
                blocked.append((pos - char_start, pos - char_start + len(p.raw)))

        if in_range:
            in_range.sort(key=lambda x: x[0])
            first_pos, first = in_range[0]
            g.fiscal = first.raw
            g.fiscal_year = first.fy_label
            g.fiscal_quarter = first.fq_label
            evidence.setdefault("FISCAL", []).append(first.raw)
            # 'from A to B' / 'A through B' / 'A - B' — treat as a single range span
            if len(in_range) >= 2:
                second_pos, second = in_range[1]
                gap = text[first_pos + len(first.raw):second_pos]
                if _LIST_CONNECTOR.fullmatch(gap):
                    g.fiscal = f"{first.raw} and {second.raw}"       # two periods in one ask: kept as typed
                    evidence.setdefault("FISCAL", []).append(second.raw)
                elif _RANGE_CONNECTOR.fullmatch(gap):
                    g.fiscal = f"{first.raw} to {second.raw}"
                    # Period labels hold the LATER endpoint so S4 can anchor the range
                    g.fiscal_year = second.fy_label or first.fy_label
                    g.fiscal_quarter = second.fq_label or first.fq_label
                    evidence.setdefault("FISCAL", []).append(second.raw)

        g.evidence = evidence
        return g, blocked

    # ── main entry ────────────────────────────────────────────────────────
    def extract(self, query: str) -> ExtractionResult:
        text = normalize(query)
        whole_doc = self._nlp(text)
        hits = self._matchers.find(whole_doc)
        # Fuzzy pass over anything the exact matcher missed — catches "EMAE"
        # for EMEA, "Americsa" for Americas, "enterprize" for Enterprise.
        fuzzy_hits = self._fuzzy_closed.find(
            whole_doc, already_hit=[(h.start, h.end) for h in hits])
        hits.extend(fuzzy_hits)
        periods = fiscal.parse(text)

        sides = comparison.split(text, self._hit_count)
        groups: list[EntityGroup] = []
        all_blocked_global: list[tuple[int, int]] = [(h.start, h.end) for h in hits]
        for p in periods:
            pos = text.lower().find(p.raw.lower())
            if pos >= 0:
                all_blocked_global.append((pos, pos + len(p.raw)))

        for side in sides:
            group, _local_blocked = self._group_for_range(
                text, side.start, side.end, hits, periods,
            )
            # Account search runs on the sub-doc for this side
            sub_doc = self._nlp(side.text)
            # Translate blocked spans into sub-doc coordinates
            local_blocked = [
                (a - side.start, b - side.start)
                for a, b in all_blocked_global
                if side.start <= a and b <= side.end
            ]
            for acct in self._accounts.find(sub_doc, local_blocked):
                group.accounts.append(acct.canon)
                group.evidence.setdefault("ACCOUNT", []).append(acct.name)
            groups.append(group)

        # Share any entity that appears in ONLY ONE group across all groups
        # — the user implied it applies to the whole comparison.
        if len(groups) > 1:
            _promote_shared(groups, ("products", "segments", "geo", "order_types"))
            _promote_fiscal(groups)

        for field, rx in _ALL_SCOPE.items():
            if rx.search(text):
                for g in groups:
                    getattr(g, field).clear()
                    g.evidence.pop(_ALL_EVIDENCE[field], None)

        op = intent_mod.operator(text)
        return ExtractionResult(
            query=query,
            intent=intent_mod.infer(
                text,
                has_account=any(g.accounts for g in groups),
                is_multi_group=len(groups) > 1 or any(" and " in (g.fiscal or "") for g in groups),
            ),
            metric=intent_mod.metric(text),
            operator=op,
            limit_n=intent_mod.limit(text, op),
            groups=groups,
        )


def _promote_fiscal(groups: list[EntityGroup]) -> None:
    """A period stated on exactly one side ('... for APAC Q1FY26') applies to all sides."""
    have = [g for g in groups if g.fiscal]
    if len(have) == 1:
        src = have[0]
        for g in groups:
            if not g.fiscal:
                g.fiscal, g.fiscal_year, g.fiscal_quarter = src.fiscal, src.fiscal_year, src.fiscal_quarter


def _promote_shared(groups: list[EntityGroup], fields: tuple[str, ...]) -> None:
    """If a filter is set on exactly one side, copy it to the others."""
    for f in fields:
        values_per_group = [getattr(g, f) for g in groups]
        populated = [v for v in values_per_group if v]
        if len(populated) == 1:
            for v in values_per_group:
                if not v:
                    v.extend(populated[0])
