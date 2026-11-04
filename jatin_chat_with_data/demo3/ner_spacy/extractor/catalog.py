"""Live product catalog loaded from `data_arr` at startup.

The hand-maintained `product_aliases` in `schema.yaml` only knows a
dozen L1 synonyms. Real production queries name L2-L5 nodes too
("Firewall ARR", "Private Access churn", "DSPM for Siemens"). We load
every distinct value at every level once per process and feed them
into the PhraseMatcher + fuzzy pass.

Fallback: a hard-coded seed list (snapshot from 2026-10-28) so the
extractor still works offline or when the DB is down.

A single product name can appear at multiple levels (e.g. "Firewall"
is L2, L3, L4 and L5). We don't resolve the hierarchy here — the
extractor just labels the span as PRODUCT with the matched text,
and `s2_resolve` (Tool 1 Product Validator) picks the actual path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional


# ── Fallback seed ─────────────────────────────────────────────────────────────
# Snapshot of SELECT DISTINCT product_lN FROM data_arr taken 2026-10-28.
# Refresh by running `_refresh_seed_from_db()` in a shell and pasting back.
_SEED_L1 = {
    "ZT Browser", "ZIA", "EOL", "Digital Experience", "Business Continuity",
    "ZPA", "Support", "Data Security", "AI Security", "ZT Cell",
    "Agentic SecOps", "ZT Cloud", "ZT Branch",
}
_SEED_L2 = {
    "AI Gateway", "Secure AI Access", "ZT Branch", "ZIA Standard", "ZT Browser",
    "ZT Microsegmentation", "ZT Branch Standard", "Agentic SecOps Core",
    "Business Continuity", "Firewall", "AI Asset Management", "ZT Workloads",
    "Deception Standard", "ZT Cell", "Digital Experience Standard",
    "ZT Browser Standard", "Core DLP", "Privileged Remote Access",
    "Endpoint Context", "ZT Workloads Gateway", "Private Access", "EOL",
    "Digital Experience", "Secure AI Apps & Infra", "Deception", "Segmentation",
    "SaaS Security", "ZT Workloads Standard", "DSPM", "SWG", "Sandbox", "B2B",
    "Support", "Threat Hunting", "Data Security Standard", "PRA Standard",
    "MDR", "App Protection",
}
_SEED_L3 = {
    "Core SWG", "DIY BCC", "Secure AI Access", "Classification Encryption",
    "ZT Branch", "ZT Browser", "Sandbox Standard", "ZT Microsegmentation",
    "ZDX", "Private Infra - ZPA", "Core ZPA", "Firewall", "AI Asset Management",
    "ZT Workloads", "Deception Standard", "ZT Cell", "Clientless",
    "ZT Browser Standard", "SSPM", "Workloads Standard", "SaaS Security Standard",
    "Privileged Remote Access", "Inline DLP Standard", "Endpoint Context",
    "ZT Workloads Gateway", "EOL", "Exposure Management", "Branch Standard",
    "Firewall Standard", "Deception", "Segmentation", "ZDX Standard",
    "Endpoint DLP", "Private Infra - ZIA", "Email DLP", "DSPM", "CASB",
    "Sandbox", "Managed BCC", "B2B", "AI Data Guard", "Agentic SOC", "Support",
    "AI Red Teaming", "Gen AI Prompt Analytics", "Inline DLP", "PRA Standard",
    "MDR", "China Premium", "ZS Threat Hunting", "App Protection",
    "AI Endpoint Security", "Professional Services", "AI Guard",
}
# L4 / L5 are long and noisy — we only use them to resolve ambiguity, not to match.
# PhraseMatcher traversal cost scales with the pattern count; L1-L3 is plenty.


@dataclass
class ProductCatalog:
    """Known product values per level. Canonical form = exact DB spelling."""
    l1: set[str] = field(default_factory=set)
    l2: set[str] = field(default_factory=set)
    l3: set[str] = field(default_factory=set)

    def all_names(self) -> set[str]:
        return self.l1 | self.l2 | self.l3

    def level_of(self, name: str) -> Optional[int]:
        """Deepest level the name appears at (prefer specific over general)."""
        n = name.strip()
        if n in self.l3:
            return 3
        if n in self.l2:
            return 2
        if n in self.l1:
            return 1
        return None


# ── Loaders ───────────────────────────────────────────────────────────────────

def from_seed() -> ProductCatalog:
    """Offline catalog from the embedded 2026-10-28 snapshot."""
    return ProductCatalog(l1=set(_SEED_L1), l2=set(_SEED_L2), l3=set(_SEED_L3))


def from_db() -> Optional[ProductCatalog]:
    """Live catalog from `t6_arr_contract`. None if the DB is unreachable."""
    try:
        from core.db import query_all
    except Exception:
        return None
    try:
        cat = ProductCatalog()
        level_map = {"L1": cat.l1, "L2": cat.l2, "L3": cat.l3}
        rows = query_all(
            "SELECT DISTINCT product AS v, level FROM t6_arr_contract "
            "WHERE is_latest = true AND product IS NOT NULL AND level IN ('L1','L2','L3')",
            {},
        )
        for r in rows:
            bucket = level_map.get((r.get("level") or "").upper())
            if bucket is not None and r.get("v"):
                bucket.add(r["v"].strip())
        return cat
    except Exception:
        return None


@lru_cache(maxsize=1)
def load(prefer_db: bool = True) -> ProductCatalog:
    """Cached top-level entry: live DB values when available, seed otherwise."""
    if prefer_db:
        cat = from_db()
        if cat and cat.all_names():
            return _merge(cat, from_seed())        # seed covers any gap
    return from_seed()


def _merge(primary: ProductCatalog, fallback: ProductCatalog) -> ProductCatalog:
    out = ProductCatalog(l1=set(primary.l1), l2=set(primary.l2), l3=set(primary.l3))
    out.l1 |= fallback.l1 - primary.all_names()
    out.l2 |= fallback.l2 - primary.all_names()
    out.l3 |= fallback.l3 - primary.all_names()
    return out
