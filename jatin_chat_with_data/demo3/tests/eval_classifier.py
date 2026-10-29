"""Accuracy of the rule-based S1 (and S0 split decisions) against the labelled dataset, with the real database.

  python3 tests/eval_classifier.py              # whole dataset, per-field accuracy + sample mismatches
  python3 tests/eval_classifier.py intent       # list every intent mismatch

Labels: intent comes from the generator's templates (or the curated old rows); company comes from the template
slot or the old label. Region / segment / product / period come from the dataset builder's own vocabulary,
which is written separately from schema.yaml and the hierarchy, so agreement is a real cross-check.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import hierarchy  # noqa: E402
from core.config import get_schema  # noqa: E402
from pipeline import s1_extract  # noqa: E402

DATASET = Path(__file__).resolve().parents[2] / "model/train1/dataset2/zscaler_arr_dataset_fixed.jsonl"
ORIG = DATASET.with_name("zscaler_arr_dataset_fixed.orig.jsonl")
CANON = {"Americas": "AMER", "AMER": "AMER", "EMEA": "EMEA", "APJ": "APJ"}


def canon_geo(items, aliases):
    return {CANON.get(aliases.get(i.upper(), i), aliases.get(i.upper(), i)) for i in items}


def norm(x):
    return " ".join(str(x).lower().split()) if x else None


def main(show: str | None) -> None:
    hierarchy.warm()
    schema = get_schema()
    aliases = schema.get("geo_aliases", {})
    old_queries = set()
    if ORIG.exists():
        for line in ORIG.read_text().splitlines():
            old_queries.add({x["role"]: x["content"] for x in json.loads(line)["messages"]}["user"])
    rows = [json.loads(line) for line in DATASET.read_text().splitlines()]
    skipped_taxonomy = 0
    acc = collections.Counter()
    src = collections.Counter()
    bad: dict[str, list] = collections.defaultdict(list)
    confusion = collections.Counter()
    for r in rows:
        m = {x["role"]: x["content"] for x in r["messages"]}
        q = m["user"].removeprefix("User query: ").removesuffix("\n\nExtract entities:")
        want = json.loads(m["assistant"])
        e = s1_extract.extract(q)
        got = {
            "intent": e.intent.value, "account": norm(e.account_raw),
            "products": {norm(p) for p in e.products_raw}, "geo": canon_geo(e.geo_raw, aliases),
            "segment": {norm(s) for s in e.segment_raw}, "fiscal": norm(e.fiscal_raw), "metric": e.metric_raw,
        }
        exp = {
            "intent": want["intent"], "account": norm(want["account_raw"]),
            "products": {norm(p) for p in want["products_raw"]}, "geo": canon_geo(want["geo_raw"], aliases),
            "segment": {norm(s) for s in want["segment_raw"]}, "fiscal": norm(want["fiscal_raw"]),
            "metric": want["metric_raw"],
        }
        for k in exp:
            if k == "products" and any(not (hierarchy.find(p) or p.upper() in schema.get("product_aliases", {}))
                                       for p in want["products_raw"]):
                skipped_taxonomy += 1      # the label names a product that is not in today's hierarchy/aliases
                continue
            acc[k, "n"] += 1
            kind = "curated" if q in old_queries else "generated"
            src[k, kind, "n"] += 1
            if got[k] == exp[k]:
                acc[k, "ok"] += 1
                src[k, kind, "ok"] += 1
            else:
                bad[k].append((q, got[k], exp[k]))
                if k == "intent":
                    confusion[(exp[k], got[k])] += 1
    print(f"{len(rows)} labelled questions ({len(old_queries & {q for q in old_queries})} curated short ones are from the original set)\n")
    print(f"  {'field':9} {'all':>16}   {'curated (short)':>18}   {'generated (long)':>18}")
    for k in ("intent", "account", "products", "geo", "segment", "fiscal", "metric"):
        n, ok = acc[k, "n"], acc[k, "ok"]
        cells = []
        for kind in ("curated", "generated"):
            kn, kok = src[k, kind, "n"], src[k, kind, "ok"]
            cells.append(f"{kok}/{kn} {100 * kok / max(kn, 1):5.1f}%")
        print(f"  {k:9} {ok:5}/{n} {100 * ok / n:5.1f}%   {cells[0]:>18}   {cells[1]:>18}")
    print(f"\n  ({skipped_taxonomy} rows excluded from the product score: the label names a product that is not in the "
          f"current hierarchy or aliases)")
    if confusion:
        print("\n  intent confusion (expected -> got):")
        for (a, b), c in confusion.most_common(8):
            print(f"    {a:9} -> {b:9} {c}")
    for k in ([show] if show else ["intent", "account", "products", "geo", "segment", "fiscal", "metric"]):
        print(f"\n── {k}: {len(bad[k])} mismatches" + ("" if show else " (first 6)"))
        for q, g, e in bad[k][: (None if show else 6)]:
            print(f"   {q!r}\n      got={g}  expected={e}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
