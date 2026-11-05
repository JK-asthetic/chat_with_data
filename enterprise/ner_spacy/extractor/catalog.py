"""Live product catalog loaded from `dim_product_hierarchy` at startup.

The hand-maintained `product_aliases` in `schema.yaml` only knows a
dozen L1 synonyms. Real production queries name L2-L5 nodes too
("Firewall ARR", "Private Access churn", "DSPM for Siemens"). We load
every distinct value at every level once per process and feed them
into the PhraseMatcher + fuzzy pass.

A single product name can appear at several levels / branches (e.g. "Firewall").
We don't resolve the hierarchy here — the extractor just labels the span as PRODUCT
with the matched text, and extraction.tools.product_tool picks the actual path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional


@dataclass
class ProductCatalog:
    """Known product names per level, from dim_product_hierarchy."""
    l1: set[str] = field(default_factory=set)
    l2: set[str] = field(default_factory=set)
    l3: set[str] = field(default_factory=set)
    l4: set[str] = field(default_factory=set)
    l5: set[str] = field(default_factory=set)

    def all_names(self) -> set[str]:
        return self.l1 | self.l2 | self.l3 | self.l4 | self.l5


def from_db() -> ProductCatalog:
    """Catalog from dim_product_hierarchy (every level, collapsed padding)."""
    from core import hierarchy
    cat = ProductCatalog()
    levels = {1: cat.l1, 2: cat.l2, 3: cat.l3, 4: cat.l4, 5: cat.l5}
    for nodes in hierarchy._index().values():
        for n in nodes:
            levels[n.level].add(n.name)
    return cat


@lru_cache(maxsize=1)
def load(prefer_db: bool = True) -> ProductCatalog:
    """Cached catalog (live DB only — there is no offline snapshot)."""
    return from_db()
