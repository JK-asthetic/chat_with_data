"""Closed-set entity matchers using spaCy PhraseMatcher.

PhraseMatcher is a fast token-trie matcher (Aho-Corasick in spirit) that
walks the token stream once per query and returns every alias hit. We
build one matcher per label (GEO, PRODUCT, SEGMENT) from `schema.yaml`
so adding a new alias is a one-line config edit — no code change.

Each hit comes back with:
  * canonical value (DB form, e.g. "Americas" for "AMER")
  * literal span the user typed (for evidence / display)
  * character offsets (for group splitting around "vs")
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from spacy.language import Language
from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc


@dataclass
class Hit:
    label:     str       # GEO | PRODUCT | SEGMENT
    canonical: str
    literal:   str       # as typed
    start:     int       # char offset
    end:       int


# 2-letter / 3-letter acronyms must match case-exact — "us" is a pronoun,
# not Americas. Longer phrases match case-insensitively.
_SHORT_ACRONYM_LEN = 3

# Everyday words that also name a product or a segment: only an explicit phrase ('Zscaler Platform') should
# count, so they are left out ('their global number', 'total platform ARR'). Same list the regex S1 uses.
_GENERIC_PRODUCT_ALIASES = {"PLATFORM", "BUNDLE", "BUNDLES", "PS"}
_AMBIGUOUS_SEGMENT_ALIASES = {"STATE", "GLOBAL", "STRATEGIC", "ENT", "COMM", "FED", "MM", "LE"}


class ClosedSetMatchers:
    """One PhraseMatcher per label, backed by `schema.yaml` alias tables."""

    def __init__(
        self,
        nlp: Language,
        schema_path: Optional[Path] = None,
        extra_product_names: Optional[set[str]] = None,
    ):
        """`extra_product_names` are DB-sourced product values (L1-L3 from
        `data_arr`); they're merged into the PRODUCT alias table using
        themselves as both alias and canonical."""
        schema_path = schema_path or Path(__file__).resolve().parents[2] / "config" / "schema.yaml"
        schema = yaml.safe_load(schema_path.read_text())
        product_aliases = {k.upper(): v for k, v in schema.get("product_aliases", {}).items()
                           if k.upper() not in _GENERIC_PRODUCT_ALIASES}
        if extra_product_names:
            for name in extra_product_names:
                product_aliases[name.upper()] = name     # 'Digital Experience' stays that node, not the ZDX alias
        self._alias_canon: dict[str, dict[str, str]] = {
            "GEO":     {k.upper(): v for k, v in schema.get("geo_aliases", {}).items()},
            "PRODUCT": product_aliases,
            "SEGMENT": {k.upper(): v for k, v in schema.get("segment_aliases", {}).items()
                        if k.upper() not in _AMBIGUOUS_SEGMENT_ALIASES},
            "ORDER_TYPE": {k.upper(): v for k, v in schema.get("order_type_aliases", {}).items()},
        }
        # Short acronyms get their own case-sensitive matcher so "us" (the
        # pronoun) is not read as "US" (Americas).
        self._mi: dict[str, PhraseMatcher] = {}
        self._mcs: dict[str, PhraseMatcher] = {}
        for label, aliases in self._alias_canon.items():
            self._mi[label] = PhraseMatcher(nlp.vocab, attr="LOWER")
            self._mcs[label] = PhraseMatcher(nlp.vocab, attr="TEXT")
            short, long = [], []
            for alias, canon in aliases.items():
                # Products are always case-insensitive (users type "zia", "zpa" etc.).
                # Other labels (GEO, SEGMENT) keep case-sensitive short matching so
                # "us" (pronoun) doesn't match "US" (Americas).
                is_short_acronym = (len(alias) <= _SHORT_ACRONYM_LEN
                                    and alias.isupper() and alias.isalpha())
                if is_short_acronym and label != "PRODUCT":
                    short.append(alias)
                    if canon != alias and canon.upper() == alias:
                        short.append(canon)          # exact-case acronym typed in its own spelling: 'IoT'
                else:
                    long.append(alias)
            if long:
                self._mi[label].add(label, [nlp.make_doc(a.lower()) for a in long])
            if short:
                self._mcs[label].add(label, [nlp.make_doc(a) for a in short])

    @property
    def alias_tables(self) -> dict[str, dict[str, str]]:
        """Expose the raw alias→canonical maps so a fuzzy pass can reuse them."""
        return self._alias_canon

    def find(self, doc: Doc) -> list[Hit]:
        hits: list[Hit] = []
        for label in self._alias_canon:
            for matcher in (self._mi[label], self._mcs[label]):
                for _match_id, start, end in matcher(doc):
                    span = doc[start:end]
                    literal = span.text
                    canonical = self._alias_canon[label].get(literal.upper(), literal)
                    hits.append(Hit(label, canonical, literal, span.start_char, span.end_char))
        return _resolve_overlaps(hits)


def _resolve_overlaps(hits: list[Hit]) -> list[Hit]:
    """Drop any hit that is strictly contained in a longer, same-position hit.

    'ZSCALER INTERNET ACCESS' (PRODUCT=ZIA) wins over nested 'INTERNET' matches.
    'LARGE ENTERPRISE' (SEGMENT) wins over nested 'ENTERPRISE'.
    Overlapping hits of DIFFERENT labels are both kept (they're independent).
    """
    hits.sort(key=lambda h: (h.start, -(h.end - h.start)))
    kept: list[Hit] = []
    for h in hits:
        drop = False
        for k in kept:
            if k.label != h.label:
                continue
            if k.start <= h.start and h.end <= k.end and (h.end - h.start) < (k.end - k.start):
                drop = True
                break
        if not drop:
            kept.append(h)
    return kept
