"""Run the questions in tests/questions.txt through demo3 and record the JSON and the result.

  python3 tests/run_questions.py                 # regex S1 (default): S0-S4, no LLM call
  python3 tests/run_questions.py --engine spacy  # the ner_spacy S1
  python3 tests/run_questions.py --full          # also S5 (LLM) + S6 (DB): adds the SQL and the rows

Add questions to tests/questions.txt (one per line; '#' lines are ignored).
Output: tests/results/<engine>_<time>.json (one record per question) and latest_<engine>.md (a simple table).
"""
import argparse
import contextlib
import io
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESULTS = HERE / "results"


def load_questions(path: Path) -> list[str]:
    lines = (ln.strip() for ln in path.read_text().splitlines())
    return [ln for ln in lines if ln and not ln.startswith("#")]


def run_question(q: str, m: dict, full: bool) -> dict:
    """One question -> {question, parts: [{text, extracted, resolved, where, sql, rows}]}. A failure is stored, not raised."""
    parts = []
    with contextlib.redirect_stdout(io.StringIO()):          # the stages print to the terminal
        try:
            texts = [s.text for s in m["s0"].plan(q).sub_queries]
        except Exception as e:
            texts = [q]
        for text in texts:
            part = {"text": text}
            try:
                ext = m["s1"].extract(text)
                part["extracted"] = ext.model_dump(mode="json")      # the same JSON the S1 panel shows
                res = m["s2"].resolve(ext)
                f = res.fiscal
                part["resolved"] = {
                    "account": res.account_filter.account_name, "geo": res.geo_filter, "segment": res.segment_filter,
                    "products": [" > ".join(p.path) for p in res.product_filter],
                    "fiscal": f.fiscal_quarter_label or f.fiscal_year_label or f.quarter_labels or None}
                _, ctx = m["s4"].build_context(res)
                part["where"], part["group_by"] = ctx.where_values, ctx.group_by
                if full:
                    gen = m["s5"].generate(ctx)
                    out = m["s6"].execute(gen.sql, ctx.limit)
                    part.update(sql=gen.sql, source=gen.source, rows=out.row_count, sample=out.rows[:5], error=out.db_error)
            except Exception as e:
                part["error"] = f"{type(e).__name__}: {e}"[:200]
            parts.append(part)
    return {"question": q, "parts": parts}


def cell(v) -> str:
    if v in (None, "", [], {}):
        return "—"
    return (", ".join(map(str, v)) if isinstance(v, list) else str(v)).replace("|", "/").replace("\n", " ")


def to_markdown(engine: str, results: list[dict], full: bool) -> str:
    head = "| # | Question | Intent | Account | Products | Geo | Segment | Fiscal | Filters | Result |"
    lines = [f"# demo3 questions — {engine} S1 — {time.strftime('%Y-%m-%d %H:%M')}", "", head, "|" + "---|" * 10]
    for n, r in enumerate(results, 1):
        for i, p in enumerate(r["parts"]):
            e, s = p.get("extracted", {}), p.get("resolved", {})
            if "error" in p:
                result = f"ERROR {p['error']}"
            elif full:
                result = f"{p.get('rows')} rows" + (f" · {p['error']}" if p.get("error") else "") if "sql" in p else "—"
            else:
                result = "ok"
            lines.append("| " + " | ".join(map(cell, [
                n if i == 0 else "", r["question"] if i == 0 else f"↳ {p['text']}", e.get("intent"),
                s.get("account") or e.get("account_raw"), s.get("products") or e.get("products_raw"),
                s.get("geo") or e.get("geo_raw"), s.get("segment") or e.get("segment_raw"),
                s.get("fiscal") or e.get("fiscal_raw"),
                p.get("where"), result])) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=str(HERE / "questions.txt"))
    ap.add_argument("--engine", choices=("regex", "spacy"), default="regex")
    ap.add_argument("--full", action="store_true", help="also run S5 (LLM) and S6 (DB)")
    args = ap.parse_args()

    os.environ["MAESTRO_S1"] = "spacy" if args.engine == "spacy" else ""     # S0 reads it at import time
    sys.path.insert(0, str(ROOT))
    from core import hierarchy
    from pipeline import s0_decompose, s2_resolve, s4_context
    if args.engine == "spacy":
        from pipeline import s1_extract_spacy as s1
    else:
        from pipeline import s1_extract as s1
    m = {"s0": s0_decompose, "s1": s1, "s2": s2_resolve, "s4": s4_context}
    if args.full:
        from pipeline import s5_generate, s6_execute
        m.update(s5=s5_generate, s6=s6_execute)
    with contextlib.redirect_stdout(io.StringIO()):
        hierarchy.warm()

    questions = load_questions(Path(args.file))
    results = []
    for n, q in enumerate(questions, 1):
        print(f"{n}/{len(questions)} {q[:70]}", file=sys.stderr)
        results.append(run_question(q, m, args.full))

    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    (RESULTS / f"{args.engine}_{stamp}.json").write_text(json.dumps(results, indent=2, default=str))
    (RESULTS / f"latest_{args.engine}.md").write_text(to_markdown(args.engine, results, args.full))
    failed = sum(1 for r in results if any("error" in p for p in r["parts"]))
    print(f"{len(results)} questions, {failed} with errors -> {RESULTS}/latest_{args.engine}.md and {args.engine}_{stamp}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
