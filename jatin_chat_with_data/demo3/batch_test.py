#!/usr/bin/env python3
"""
Batch tester — runs 20 varied questions through the full pipeline
and prints a structured report: SQL generated, rows returned, and any errors.

Usage:  python batch_test.py
"""
from __future__ import annotations

import json
import sys
import time
import textwrap
from unittest.mock import patch

# ── Patch clarify() before importing main pipeline modules ───────────────────
# Forces auto-accept (no terminal prompt) for batch testing.
# If S3 would normally ask the user, we auto-pick the first match or continue without.
def _auto_clarify(resolved):
    """Non-interactive S3: accept first company match or continue without filter."""
    from pipeline.s3_clarify import ClarifyResult, _classify, _ALL_ACCOUNTS
    from pipeline.models import AccountFilter

    answerable, reason = _classify(resolved)

    # If company is ambiguous, auto-pick top match
    if resolved.company_ambiguous and resolved.company_matches:
        top = resolved.company_matches[0]
        resolved = resolved.model_copy(update={
            "account_filter": AccountFilter(
                account_raw  = top.account_name,
                account_id   = top.account_id,
                account_name = top.account_name,
            ),
            "company_ambiguous": False,
        })
        answerable = True
        reason = ""

    return ClarifyResult(
        answerable          = answerable,
        not_answerable_reason = reason if not answerable else "",
        addendum            = None,
        cancelled           = False,
    )


# 20 test questions — varied across intent, metric, geo, segment, SKU, renewal
QUESTIONS = [
    # ── ARR snapshots ─────────────────────────────────────────────────────────
    "Top 10 accounts by ARR in FY 2026 Q1",
    "Top 20 accounts by ARR in EMEA for FY 2026",
    "What is the total ARR breakdown by product in Americas FY 2026 Q2?",
    "Show me ARR by market segment for Enterprise customers in FY 2026 Q1",
    "Which accounts have the highest ARR in the APJ region FY 2026 Q3?",

    # ── Trend / Delta ─────────────────────────────────────────────────────────
    "Show ARR trend by quarter from FY 2025 Q1 to FY 2026 Q4",
    "What is the QoQ ARR growth for ZIA product in FY 2026?",
    "Compare ARR between FY 2025 Q4 and FY 2026 Q1 by geo",

    # ── Churn / Downsell ──────────────────────────────────────────────────────
    "Which accounts churned the most ARR in FY 2026 Q2?",
    "Show me the top 15 downsell accounts in EMEA for FY 2026",

    # ── SKU / item_name ───────────────────────────────────────────────────────
    "What is the ARR for ZIA-BIZ-EDITION in FY 2026 Q1?",
    "Show me ARR breakdown for ZPA-BIZ-EDITION and ZIA-TRANS-EDITION by account",
    "Which accounts are using ZS-DP-1 SKU and how much ARR?",

    # ── Renewal / end_date ────────────────────────────────────────────────────
    "Which contracts are renewing between January 2027 and March 2027?",
    "Show me upcoming renewals in FY 2027 Q1 with the ARR at stake",
    "List all renewal contracts expiring in FY 2027 Q2",

    # ── Segment + product ─────────────────────────────────────────────────────
    "Show ARR for ZPA product in Commercial segment FY 2026 Q1",
    "What is the incremental ARR for new logo accounts in FY 2026?",

    # ── Lookup / risk ─────────────────────────────────────────────────────────
    "What is the ARR breakdown by product for all accounts in FY 2026 Q1?",
    "Which accounts have declining ARR trend from FY 2025 Q4 to FY 2026 Q4?",
]


def run_one(question: str, idx: int) -> dict:
    """Run a single question through S1→S2→S3(auto)→S4→S5→S6 and return summary."""
    import os
    os.chdir("/Users/jatinkhetan/Desktop/Chat with data/jatin_chat_with_data/demo3")

    from pipeline import s1_extract, s2_resolve, s4_context, s5_generate, s6_execute
    import io, contextlib

    result = {
        "idx":       idx,
        "question":  question,
        "intent":    "?",
        "metric":    "?",
        "metric_prompt": "?",
        "where":     {},
        "group_by":  [],
        "sql":       "",
        "sql_source": "",
        "rows":      0,
        "elapsed_ms": 0,
        "db_error":  None,
        "error":     None,
    }

    t0 = time.perf_counter()
    buf = io.StringIO()

    try:
        with contextlib.redirect_stdout(buf):
            # S1
            extracted = s1_extract.extract(question)
            result["intent"]  = extracted.intent.value
            result["metric"]  = extracted.metric_raw

            # S2
            resolved_base = s2_resolve.resolve(extracted)

            # S3 (auto)
            resolved = resolved_base
            if resolved_base.company_ambiguous and resolved_base.company_matches:
                from pipeline.models import AccountFilter
                top = resolved_base.company_matches[0]
                resolved = resolved_base.model_copy(update={
                    "account_filter": AccountFilter(
                        account_raw  = top.account_name,
                        account_id   = top.account_id,
                        account_name = top.account_name,
                    ),
                    "company_ambiguous": False,
                })

            # S4
            enriched, ctx = s4_context.build_context(resolved)
            result["where"]    = ctx.where_values
            result["group_by"] = ctx.group_by

            # Which metric prompt was selected?
            from pipeline.s5_generate import _metric_prompt
            mp = _metric_prompt(ctx)
            result["metric_prompt"] = mp.splitlines()[0].replace("### Metric: ", "")

            # S5
            gen = s5_generate.generate(ctx)
            result["sql"]        = gen.sql
            result["sql_source"] = gen.source

            # S6
            qr = s6_execute.execute(gen.sql, ctx.limit)
            result["rows"]     = qr.row_count
            result["db_error"] = qr.db_error

    except Exception as e:
        result["error"] = str(e)

    result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
    return result


def fmt_sql(sql: str, width: int = 90) -> str:
    """Compact SQL display."""
    sql = sql.strip().replace("\n", " ").replace("  ", " ")
    return textwrap.shorten(sql, width=width, placeholder=" …")


def print_report(results: list[dict]) -> None:
    sep = "─" * 110
    print(f"\n{'═' * 110}")
    print(f"  BATCH TEST REPORT  —  {len(results)} questions")
    print(f"{'═' * 110}")

    for r in results:
        status = "✗ ERROR" if r["error"] or r["db_error"] else "✓"
        print(f"\n{sep}")
        print(f"  Q{r['idx']:02d}  {r['question']}")
        print(f"  {'─' * 106}")
        print(f"  Intent:        {r['intent']}   |  Metric: {r['metric']}   |  Prompt: {r['metric_prompt']}")
        print(f"  WHERE:         {json.dumps(r['where'], default=str)[:100]}")
        print(f"  GROUP BY:      {r['group_by']}")
        print(f"  SQL ({r['sql_source']}):  {fmt_sql(r['sql'])}")
        print(f"  Result:        {status}  rows={r['rows']}  elapsed={r['elapsed_ms']}ms")
        if r["db_error"]:
            print(f"  DB Error:      {r['db_error'][:120]}")
        if r["error"]:
            print(f"  Pipeline Err:  {r['error'][:120]}")

    # Summary table
    ok     = sum(1 for r in results if not r["error"] and not r["db_error"])
    dberr  = sum(1 for r in results if r["db_error"])
    piperr = sum(1 for r in results if r["error"])
    total_ms = sum(r["elapsed_ms"] for r in results)

    print(f"\n{'═' * 110}")
    print(f"  SUMMARY   OK={ok}/{len(results)}   DB errors={dberr}   Pipeline errors={piperr}   Total time={total_ms/1000:.1f}s")

    # Metric prompt routing summary
    prompt_counts: dict[str, int] = {}
    for r in results:
        p = r["metric_prompt"]
        prompt_counts[p] = prompt_counts.get(p, 0) + 1
    print(f"  Prompt routing:  {dict(sorted(prompt_counts.items()))}")
    print(f"{'═' * 110}\n")


if __name__ == "__main__":
    import os
    os.chdir("/Users/jatinkhetan/Desktop/Chat with data/jatin_chat_with_data/demo3")
    sys.path.insert(0, ".")

    print(f"\nRunning {len(QUESTIONS)} questions through the pipeline...\n")
    results = []
    for i, q in enumerate(QUESTIONS, 1):
        print(f"  [{i:02d}/{len(QUESTIONS)}] {q[:80]}", end="", flush=True)
        r = run_one(q, i)
        status = "✓" if not r["error"] and not r["db_error"] else "✗"
        print(f"  {status}  {r['elapsed_ms']}ms  rows={r['rows']}")
        results.append(r)

    print_report(results)
