"""Product hierarchy from dim_product_hierarchy (L1..L5) — the single source for product classification.

A node is identified by its full path (l1..lk). The table pads shallow branches by repeating the
parent value (ZT Browser / ZT Browser / ZT Browser ...), so a level whose value equals its parent
is not a separate node. The same name can still exist in several branches / levels
(e.g. 'B2B'), which is exactly the ambiguity callers must surface to the user.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz, process

from core.db import query_all


@dataclass(frozen=True)
class Node:
    level: int
    path: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.path[-1]

    @property
    def display(self) -> str:
        out: list[str] = []
        for p in self.path:
            if not out or out[-1] != p:
                out.append(p)
        return " > ".join(out)


@lru_cache(maxsize=1)
def _index() -> dict[str, tuple[Node, ...]]:
    rows = query_all(
        "SELECT DISTINCT product_l1, product_l2, product_l3, product_l4, product_l5 FROM dim_product_hierarchy"
    )
    nodes: dict[tuple[str, ...], Node] = {}
    for r in rows:
        vals = [(r.get(f"product_l{i}") or "").strip() for i in range(1, 6)]
        for k in range(1, 6):
            v = vals[k - 1]
            if not v:
                break
            if k > 1 and v == vals[k - 2]:
                continue
            prefix = tuple(vals[:k])
            nodes[prefix] = Node(k, prefix)
    index: dict[str, list[Node]] = defaultdict(list)
    for n in nodes.values():
        index[n.name.lower()].append(n)
    return {k: tuple(sorted(v, key=lambda n: (n.level, n.path))) for k, v in index.items()}


def find(name: str) -> list[Node]:
    """Every node whose name equals `name` (case-insensitive), shallowest first."""
    return list(_index().get(name.strip().lower(), ()))


def fuzzy(name: str, cutoff: float = 88.0) -> list[Node]:
    """Nodes of the best typo-tolerant name match(es)."""
    keys = list(_index().keys())
    hits = process.extract(name.strip().lower(), keys, scorer=fuzz.ratio, score_cutoff=cutoff, limit=3)
    if not hits:
        return []
    top = hits[0][1]
    return [n for key, score, _ in hits if score >= top - 1e-9 for n in _index()[key]]


def matchable_names() -> list[str]:
    """Display-case names of all nodes (feeds the NER product matcher)."""
    return sorted({n.name for nodes in _index().values() for n in nodes})
