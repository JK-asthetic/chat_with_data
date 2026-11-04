"""CLI tester for the extractor.

Usage:
    python cli.py                                    # self-check
    python cli.py "ARR for Toyota in EMEA Q1FY26"
    python cli.py --json "..."
    python cli.py --file queries.txt
    python cli.py --live "..."                       # confirm accounts via dim_account

By default runs with a tiny built-in company list so no DB is needed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extractor import Extractor


_FAKE_KNOWN = [
    "Toyota", "BMW", "Siemens", "Siemens AG", "Microsoft", "Google",
    "Bank of America", "Shell", "PayPal", "Cisco", "Royal Bank of Canada",
    "HSBC", "JPMorgan", "Goldman Sachs", "Deutsche Bank",
]


def _render(res) -> str:
    lines = [
        f"query:    {res.query}",
        f"intent:   {res.intent}    metric: {res.metric}    "
        f"operator: {res.operator or '—'}    limit: {res.limit_n or '—'}    "
        f"comparison: {res.is_comparison}",
    ]
    for i, g in enumerate(res.groups, 1):
        tag = f"group {i}" if res.is_comparison else "entities"
        lines += [
            f"  [{tag}]",
            f"    accounts  {', '.join(g.accounts) or '—'}",
            f"    products  {', '.join(g.products) or '—'}",
            f"    geo       {', '.join(g.geo) or '—'}",
            f"    segments  {', '.join(g.segments) or '—'}",
            f"    ordertype {', '.join(g.order_types) or '—'}",
            f"    fiscal    {g.fiscal or '—'}   (year: {g.fiscal_year or '—'}, qtr: {g.fiscal_quarter or '—'})",
        ]
    return "\n".join(lines)


_SELFCHECK = [
    "ARR for Toyota in EMEA Q1FY26",
    "Top 10 accounts by ZPA ARR in APJ enterprise last 4 quarters",
    "What is the ARR for ZTNA in Americas FY 2026?",
    "Compare ARR for companies in EMEA in 2026 vs companies in AMER in 2027",
    "Which EMEA large enterprise accounts had Data Security downsell greater than 500K Q1FY26?",
    "Siemnes ARR Q1FY26",   # typo -> fuzzy to Siemens
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--live", action="store_true",
                    help="Confirm accounts via core.companies.existing (hits DB)")
    args = ap.parse_args()

    lookup = None
    known = _FAKE_KNOWN
    if args.live:
        try:
            from core.companies import existing
            lookup = existing
            known = []     # DB is authoritative; local list only for fuzzy
        except Exception as e:
            print(f"warning: --live failed ({e}); falling back to fake list", file=sys.stderr)

    ex = Extractor(lookup=lookup, known_companies=known)

    queries: list[str] = []
    if args.query:
        queries.append(args.query)
    if args.file:
        queries += [ln.strip() for ln in Path(args.file).read_text().splitlines() if ln.strip()]
    if not queries:
        queries = _SELFCHECK

    if args.json:
        print(json.dumps([ex.extract(q).to_dict() for q in queries], indent=2))
    else:
        for q in queries:
            print(_render(ex.extract(q)))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
