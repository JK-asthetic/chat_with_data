"""Standalone NER tester for Chat with Data.

Extracts named entities only — accounts, products, geo, segments, fiscal
period — from a query, without running the rest of the pipeline (no intent,
no SQL, no DB). Reuses `s1_extract.find_slots`, which is the same code
production S1 uses to recognise entities.

Usage:
  python3 tests/test_ner.py                                   # self-check
  python3 tests/test_ner.py "ARR for Toyota in EMEA Q1FY26"   # one query
  python3 tests/test_ner.py --file queries.txt                # one per line
  python3 tests/test_ner.py --json "..."                      # machine output
  python3 tests/test_ner.py --live "..."                      # hit real DB
                                                              # (default: fake
                                                              # hierarchy +
                                                              # account list)

By default the script installs the test fixture hierarchy and a small fake
account list so it runs hermetically — no Postgres needed. Pass --live to
use the real `core.companies` / `core.hierarchy` against the configured DB.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import companies, hierarchy  # noqa: E402
from pipeline import s1_extract  # noqa: E402

import fixtures  # noqa: E402


_FAKE_ACCOUNTS = {
    "toyota", "bmw", "siemens", "siemens ag", "microsoft", "google",
    "bank of america", "shell", "paypal", "cisco", "royal bank of canada",
}


def _install_fakes() -> None:
    """Fixture hierarchy + a small in-memory account list. Hermetic."""
    fixtures.install_hierarchy()
    hierarchy._INDEX = hierarchy.build_index(fixtures.ROWS + [dict(zip(
        ("product_l1", "product_l2", "product_l3", "product_l4", "product_l5"),
        (n, n, n, n, n))) for n in ("Data Security", "Agentic SecOps", "ZT Branch")])
    companies.existing = lambda cands, exact=False: {
        c.lower() for c in cands if c.lower() in _FAKE_ACCOUNTS}


def ner(query: str) -> dict:
    """Entities only: {accounts, products, geo, segments, fiscal}."""
    return s1_extract.find_slots(query)


def _render(query: str, slots: dict) -> str:
    def fmt(v):
        if not v:
            return "—"
        return ", ".join(v) if isinstance(v, list) else str(v)
    return (
        f"query     {query}\n"
        f"  accounts  {fmt(slots['accounts'])}\n"
        f"  products  {fmt(slots['products'])}\n"
        f"  geo       {fmt(slots['geo'])}\n"
        f"  segments  {fmt(slots['segments'])}\n"
        f"  fiscal    {fmt(slots['fiscal'])}\n"
    )


# ── Self-check cases (one line per expected entity type) ─────────────────────
# ponytail: tiny smoke set, not a full regression suite — test_s1_rules.py
# already covers depth; this just proves the NER wrapper wires through.
_CASES: list[tuple[str, dict]] = [
    ("ARR for Toyota in EMEA Q1FY26",
     {"accounts": ["Toyota"], "geo": ["EMEA"], "fiscal": "Q1FY26"}),
    ("Top 10 accounts by ZPA ARR in APJ enterprise last 4 quarters",
     {"products": ["ZPA"], "geo": ["APJ"], "segments": ["enterprise"],
      "fiscal": "last 4 quarters"}),
    ("Compare Siemens and BMW ARR for FY26",
     {"accounts": ["Siemens", "BMW"], "fiscal": "FY26"}),
    ("What is the Core SWG ARR for Shell?",
     {"accounts": ["Shell"], "products": ["Core SWG"]}),
]


def _selfcheck() -> int:
    fails = 0
    for q, want in _CASES:
        got = ner(q)
        bad = {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}
        status = "OK  " if not bad else "FAIL"
        print(f"[{status}] {q}")
        if bad:
            fails += 1
            for k, (g, w) in bad.items():
                print(f"         {k}: got {g!r} expected {w!r}")
    print(f"\n{len(_CASES) - fails}/{len(_CASES)} passed")
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Chat-with-data NER tester")
    ap.add_argument("query", nargs="?", help="Query to extract entities from")
    ap.add_argument("--file", help="File of queries, one per line")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of pretty text")
    ap.add_argument("--live", action="store_true",
                    help="Use real hierarchy + account list (hits DB)")
    args = ap.parse_args()

    if not args.live:
        _install_fakes()

    if not args.query and not args.file:
        return _selfcheck()

    queries: list[str] = []
    if args.query:
        queries.append(args.query)
    if args.file:
        queries.extend(ln.strip() for ln in Path(args.file).read_text().splitlines() if ln.strip())

    if args.json:
        print(json.dumps([{"query": q, **ner(q)} for q in queries], indent=2))
    else:
        for q in queries:
            print(_render(q, ner(q)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
