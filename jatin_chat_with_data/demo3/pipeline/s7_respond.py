"""
Stage 7 — Sanity Checks + Insight Generation + Terminal Display.

8A. Statistical sanity checks (deterministic, no model)
8B. LLM insight generator (Ollama, 2-3 sentences, grounded only)
8C. Auto chart-type rule (pure logic)
9.  Terminal display
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Literal

import requests

from core.config import get_settings
from pipeline.models import (
    GeneratedSQL,
    PipelineResponse,
    QueryResult,
    SQLContext,
    SanityWarning,
)

# ── Colours ───────────────────────────────────────────────────────────────────
_G  = "\033[92m"   # green
_Y  = "\033[93m"   # yellow
_R  = "\033[91m"   # red
_C  = "\033[96m"   # cyan
_B  = "\033[1m"    # bold
_D  = "\033[2m"    # dim
_RS = "\033[0m"    # reset
_W  = 76           # box width


# ── 8A: Sanity checks ─────────────────────────────────────────────────────────

def sanity_check(result: QueryResult, ctx: SQLContext) -> list[SanityWarning]:
    warnings: list[SanityWarning] = []

    if not result.success or not result.rows:
        return warnings

    # S1: Zero rows with filters
    if result.row_count == 0 and ctx.where_values:
        filter_str = ", ".join(f"{k}='{v}'" for k, v in ctx.where_values.items())
        warnings.append(SanityWarning(
            code="S1_ZERO_ROWS",
            message=f"0 rows returned with filters: {filter_str}. "
                    "Check filter values or try removing some.",
        ))
        return warnings

    # Numeric values — look for arr / total_arr column
    metric_col = next((c for c in result.columns
                       if "arr" in c.lower() and c.lower() != "arr_change"), None)
    if not metric_col:
        return warnings

    try:
        values = [float(r[metric_col]) for r in result.rows if r.get(metric_col) is not None]
    except (TypeError, ValueError):
        return warnings

    if not values:
        return warnings

    total = sum(values)

    # S2: Single row dominates
    if total > 0 and len(values) > 1:
        dominant = max(values) / total
        if dominant > 0.5:
            top_name = result.rows[values.index(max(values))].get(
                "account_name", result.rows[values.index(max(values))].get("end_user_name", "One account")
            )
            warnings.append(SanityWarning(
                code="S2_OUTLIER",
                message=f"{top_name} represents {dominant:.0%} of total shown. "
                        "Consider checking if a parent entity is double-counted.",
            ))

    # S3: ARR value range sanity
    avg = total / len(values)
    if avg < 100:
        warnings.append(SanityWarning(
            code="S3_SUSPICIOUSLY_LOW",
            message=f"Average ARR value is ${avg:,.0f} — likely missing SUM() or grouping issue.",
        ))
    if total > 50_000_000_000:
        warnings.append(SanityWarning(
            code="S3_SUSPICIOUSLY_HIGH",
            message=f"Total ARR shown is ${total/1e9:.1f}B — may be double-counting across product lines.",
        ))

    # S4: Row count vs requested limit
    expected = ctx.limit
    if result.row_count > expected * 2:
        warnings.append(SanityWarning(
            code="S4_ROW_COUNT",
            message=f"Got {result.row_count} rows but asked for {expected}. LIMIT may not have applied.",
        ))

    return warnings


# ── 8B: LLM insight ──────────────────────────────────────────────────────────

_INSIGHT_SYSTEM = """\
You are a data analyst answering a user's question directly from query results.

Rules:
- If the result is a single value, answer in ONE sentence: state the number and what it represents.
- If the result is a list/table, write 2-3 sentences: lead with the most notable finding, then context.
- Be factual — only reference numbers from the rows provided. Never fabricate or estimate.
- Do not repeat the question verbatim.
- Dollar amounts in the rows are ALREADY formatted ($94.8K, $2.9M). Copy them exactly; never rescale.
- Use product names exactly as written (ZIA, ZPA, ZDX, ...). Never expand or explain acronyms.
- For ranked results, name the top 2-3 entries with their values.
"""

_MERGE_SYSTEM = """\
You answer one user question that was split into several parts, each answered by its own query.
Write a short answer to the ORIGINAL question: one line per part, in order, formatted "Part N - <what it measures>: <answer>".
For a ranked list, name the entries with their values.
Use ONLY numbers and names from the rows provided. If a part has no data or failed, say so plainly for that part - never estimate.
Dollar amounts in the rows are ALREADY formatted ($94.8K, $2.9M). Copy them exactly; never rescale or convert units.
Never expand or explain acronyms (ZIA, ZPA, ZDX, ...). Do not add advice or extra analysis.
"""


_MONEY_COLS = ("arr", "acv", "total", "change")


def humanize_rows(rows: list[dict]) -> list[dict]:
    """Format money columns in code ($94.8K), so the LLM copies numbers instead of scaling them (it once said $94.8M)."""
    out = []
    for r in rows:
        out.append({k: (_fmt_num(v) if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
                        and any(m in k.lower() for m in _MONEY_COLS) else v) for k, v in r.items()})
    return out


def generate_insight(result: QueryResult, question: str) -> str:
    """Stream a 2-3 sentence insight for one result to the terminal; returns the full text."""
    if not result.success or not result.rows:
        return ""
    rows_json = json.dumps(humanize_rows(result.rows[:20]), default=str)
    user_msg = (
        f"Question: {question}\n\n"
        f"Result rows (max 20):\n{rows_json}\n\n"
        "Write a 2-3 sentence factual insight:"
    )
    return _stream(_INSIGHT_SYSTEM, user_msg, "💡 Insight:", max_tokens=200)


def generate_merged_insight(original: str, parts: list[tuple[str, QueryResult | None, str]]) -> str:
    """One combined answer for a multi-part question. `parts` = (sub-question, result or None, note)."""
    blocks = []
    for i, (text, res, note) in enumerate(parts, 1):
        if res is not None and res.success and res.rows:
            blocks.append(f"Part {i}: {text}\nRows (max 10): {json.dumps(humanize_rows(res.rows[:10]), default=str)}")
        else:
            blocks.append(f"Part {i}: {text}\nNO DATA - {note or 'no rows returned'}")
    user_msg = f"Original question: {original}\n\n" + "\n\n".join(blocks) + "\n\nAnswer:"
    return _stream(_MERGE_SYSTEM, user_msg, "💡 Combined answer:", max_tokens=400)


def _stream(system: str, user_msg: str, label: str, max_tokens: int) -> str:
    """Stream tokens from ZLLAMA straight to the terminal. Optional by design: failure returns ''."""
    cfg = get_settings()
    try:
        base = cfg.ZLLAMA_BASE_URL.rstrip("/")
        print(f"\n  {_C}{label}{_RS} ", end="", flush=True)
        resp = requests.post(
            f"{base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {cfg.ZLLAMA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": cfg.ZLLAMA_INSIGHT_MODEL,
                "temperature": 0,
                "max_tokens": max_tokens,
                "stream": True,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            },
            stream=True,
            timeout=(5, 30),
        )
        resp.raise_for_status()

        full_text = ""
        for raw_line in resp.iter_lines():  # SSE: "data: {...}" lines, then "data: [DONE]"
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                token = json.loads(payload)["choices"][0]["delta"].get("content", "")
            except (KeyError, json.JSONDecodeError):
                continue
            if token:
                print(token, end="", flush=True)
                full_text += token
        print()
        return full_text.strip()
    except Exception:
        print()
        return ""


# ── 8C: Auto chart type ───────────────────────────────────────────────────────

def auto_chart_type(
    result: QueryResult,
    ctx: SQLContext,
) -> Literal["table", "bar", "line", "stat_card", "scatter"]:
    """Pure logic — no model needed."""
    if result.row_count == 0:
        return "table"
    if result.row_count == 1 and len(result.columns) <= 2:
        return "stat_card"

    time_cols = {"fiscal_year", "fiscal_quarter", "fiscal_month"}
    has_time  = any(c in time_cols for c in result.columns)
    num_cols  = sum(1 for c in result.columns
                    if any(m in c.lower() for m in ("arr", "acv", "count", "total")))

    if has_time and num_cols >= 1:
        return "line"
    if num_cols >= 2:
        return "scatter"
    if num_cols == 1:
        return "bar"
    return "table"


# ── 9: Terminal display ───────────────────────────────────────────────────────

_ARR_MARKERS = ("arr", "acv", "revenue", "renewal_arr", "q2_2027_renewal_arr")
_PCT_MARKERS = ("pct", "percent", "rate", "share", "pct_")
_COUNT_MARKERS = ("count", "qty", "quantity", "num_", "number_")


def _fmt_money(val) -> str:
    try:
        f = float(val)
        if f >= 1_000_000:
            return f"${f/1_000_000:,.1f}M"
        if f >= 1_000:
            return f"${f/1_000:,.1f}K"
        return f"${f:,.0f}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_pct(val) -> str:
    try:
        return f"{float(val):,.1f}%"
    except (TypeError, ValueError):
        return str(val)


def _fmt_count(val) -> str:
    try:
        return f"{int(float(val)):,}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_num(val) -> str:
    """Legacy alias used by humanize_rows — always money format."""
    return _fmt_money(val)


def _col_kind(col: str) -> str:
    """Classify a column name as 'money', 'pct', 'count', or 'plain'."""
    c = col.lower()
    if any(m in c for m in _PCT_MARKERS):
        return "pct"
    if any(m in c for m in _ARR_MARKERS):
        return "money"
    if any(m in c for m in _COUNT_MARKERS):
        return "count"
    return "plain"


def _display_stat_card(result: QueryResult) -> None:
    """Single-value result: show as a clean formatted number, not a table row."""
    if not result.rows:
        return
    row = result.rows[0]
    metric_col = next(
        (c for c in result.columns if _col_kind(c) in ("money", "count")),
        None,
    )
    label_col = next(
        (c for c in result.columns if _col_kind(c) == "plain"),
        None,
    )
    if metric_col:
        val = row.get(metric_col)
        kind = _col_kind(metric_col)
        if kind == "money":
            fmt_val = _fmt_money(val)
        elif kind == "count":
            fmt_val = _fmt_count(val)
        else:
            fmt_val = str(val)
        label = str(row.get(label_col, "")) if label_col else ""
        print(f"\n  {_B}{fmt_val}{_RS}", end="")
        if label:
            print(f"  {_D}— {label}{_RS}", end="")
        print()
    else:
        _display_table(result)


def _display_table(result: QueryResult) -> None:
    if not result.rows:
        print(f"  {_Y}No rows returned.{_RS}")
        return

    kinds = {c: _col_kind(c) for c in result.columns}

    def _fmt(col: str, val) -> str:
        if val is None or val == "":
            return "—"
        k = kinds[col]
        if k == "money":
            return _fmt_money(val)
        if k == "pct":
            return _fmt_pct(val)
        if k == "count":
            return _fmt_count(val)
        return str(val)

    col_widths = {c: max(len(c), 8) for c in result.columns}
    for row in result.rows:
        for c in result.columns:
            col_widths[c] = max(col_widths[c], len(_fmt(c, row.get(c, ""))))

    # Header
    header = "  " + "  ".join(c.upper().ljust(col_widths[c]) for c in result.columns)
    print(f"\n{_B}{header}{_RS}")
    print("  " + "  ".join("─" * col_widths[c] for c in result.columns))

    # Rows
    for row in result.rows:
        parts = [_fmt(c, row.get(c, "")).ljust(col_widths[c]) for c in result.columns]
        print("  " + "  ".join(parts))


def display(response: PipelineResponse, show_sql: bool = False, show_header: bool = True) -> None:
    """Render the full terminal response."""
    ctx     = response.context
    result  = response.result
    gen     = response.generated

    if show_header:
        print(f"\n  {'─' * _W}")
        print(f"  {_B}{ctx.normalized_question}{_RS}")
        print(f"  {'─' * _W}")

    # Sanity warnings
    for w in response.sanity_warnings:
        print(f"\n  {_Y}⚠  {w.message}{_RS}")

    # DB error
    if result.db_error:
        print(f"\n  {_R}✗  DB error: {result.db_error}{_RS}")
    elif not result.rows:
        print(f"\n  {_Y}No data returned.{_RS}")
        if ctx.where_values:
            print(f"  {_D}Filters applied: {ctx.where_values}{_RS}")
    else:
        if response.chart_type == "stat_card":
            _display_stat_card(result)
        else:
            _display_table(result)
        # insight already printed live during streaming — skip re-printing

    # Metadata footer
    source_badge = f"{_G}llm{_RS}" if gen.source == "llm" else f"{_Y}fallback{_RS}"
    print(f"\n  {_D}rows: {result.row_count}  "
          f"| time: {result.elapsed_ms:.0f}ms  "
          f"| source: {source_badge}  "
          f"| chart: {response.chart_type}{_RS}")

    if gen.source == "fallback" and gen.validation_errors:
        print(f"  {_Y}  LLM SQL failed validation — used deterministic skeleton.{_RS}")

    if show_sql:
        print(f"\n  {_D}── SQL ──────────────────────────────────────────────{_RS}")
        for line in result.sql.split("\n"):
            print(f"  {_D}{line}{_RS}")
        print(f"  {_D}────────────────────────────────────────────────────{_RS}")


def display_part(response: PipelineResponse, index: int, total: int, text: str, show_sql: bool = False) -> None:
    """One part of a multi-part answer: label, then the usual table/footer."""
    print(f"\n  {_B}{_C}━━ Part {index}/{total} ━━{_RS}  {text}")
    display(response, show_sql=show_sql, show_header=False)


def display_part_failure(index: int, total: int, text: str, reason: str) -> None:
    print(f"\n  {_B}{_C}━━ Part {index}/{total} ━━{_RS}  {text}")
    print(f"\n  {_R}✗  {reason}{_RS}")
