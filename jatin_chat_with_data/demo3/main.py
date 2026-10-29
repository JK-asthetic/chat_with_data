#!/usr/bin/env python3
"""
ARR Analytics — Terminal Pipeline
══════════════════════════════════
Entry point: orchestrates all 7 pipeline stages.

Usage:
  python main.py                      # interactive REPL
  python main.py "top 10 ARR in EMEA FY 2026 Q1"   # single query

Stages:
  S1 Extract    → fiscal normalize + LLM entity extraction
  S2 Resolve    → parallel company/fiscal/geo resolution
  S3 Clarify    → single terminal clarification card (if needed)
  S4 Context    → deterministic schema linker → SQLContext JSON
  S5 Generate   → SQLCoder + validator + retry loop
  S6 Execute    → Postgres read-only execution
  S7 Respond    → sanity checks + insight + display
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
import time
from dataclasses import dataclass, field

# ── Stage imports ─────────────────────────────────────────────────────────────
from core import hierarchy
import os
from pipeline import s2_resolve, s3_clarify, s4_context
# S1 engine: `MAESTRO_S1=spacy python main.py ...` uses the no-training
# ner_spacy extractor; otherwise fall back to the regex-based S1.
if os.environ.get("MAESTRO_S1", "").lower() == "spacy":
    from pipeline import s1_extract_spacy as s1_extract
else:
    from pipeline import s1_extract
from pipeline import s0_decompose, s5_generate, s6_execute, s7_respond
from pipeline.models import DecompositionPlan, PipelineResponse
from pipeline.run_log import SessionLogger
from core.memory import SessionMemory, Turn, account_column

# ── Colours ───────────────────────────────────────────────────────────────────
_B  = "\033[1m"
_C  = "\033[96m"
_G  = "\033[92m"
_Y  = "\033[93m"
_R  = "\033[91m"
_D  = "\033[2m"
_RS = "\033[0m"
_W  = 76


USE_MEMORY = False   # demo: every question is a fresh call. True enables follow-ups ("the second one", "and for APJ?")
_VERBOSE = True   # False while running the parts of a multi-part question (the plan view replaces step output)


def _vprint(label: str, data: dict | list | str) -> None:
    """Print a compact verbose block after each stage."""
    if not _VERBOSE:
        return
    import json
    print(f"    {_D}┌─ {label} {'─' * max(0, 50 - len(label))}┐{_RS}")
    if isinstance(data, str):
        for line in data.splitlines():
            print(f"    {_D}│  {line}{_RS}")
    elif isinstance(data, (dict, list)):
        text = json.dumps(data, default=str, indent=None)
        # Pretty-print key: value pairs for dicts
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"    {_D}│  {k:<22} {v}{_RS}")
        else:
            for item in data:
                print(f"    {_D}│  {item}{_RS}")
    print(f"    {_D}└{'─' * 52}┘{_RS}")


# ── Progress printer ──────────────────────────────────────────────────────────

class _Step:
    def __init__(self, n: int, total: int, label: str):
        self.n     = n
        self.total = total
        self.label = label
        self._t0   = time.perf_counter()
        if _VERBOSE:
            print(f"  [{n}/{total}] {label:<35}", end="", flush=True)

    def done(self, note: str = "") -> None:
        if not _VERBOSE:
            return
        elapsed = time.perf_counter() - self._t0
        suffix  = f"  {_D}{note}{_RS}" if note else ""
        print(f"  {_G}✓{_RS}  {elapsed:.1f}s{suffix}")

    def warn(self, note: str) -> None:
        if not _VERBOSE:
            return
        elapsed = time.perf_counter() - self._t0
        print(f"  {_Y}⚠{_RS}  {elapsed:.1f}s  {_Y}{note}{_RS}")

    def fail(self, msg: str) -> None:
        if not _VERBOSE:
            return
        elapsed = time.perf_counter() - self._t0
        print(f"  {_R}✗{_RS}  {elapsed:.1f}s  {_R}{msg}{_RS}")


# ── Pipeline orchestrator ─────────────────────────────────────────────────────

def _quiet():
    """Swallow stage chatter (spinners, raw JSON) while running the parts of a multi-part question."""
    return contextlib.nullcontext() if _VERBOSE else contextlib.redirect_stdout(io.StringIO())


def _entities(resolved) -> dict:
    """What the pipeline actually resolved, saved to session memory so follow-ups can inherit it."""
    fq = resolved.fiscal
    return {
        "intent":   resolved.extracted.intent.value,
        "account":  resolved.account_filter.account_name,
        "products": [" > ".join(p.path) for p in resolved.product_filter],
        "geo":      list(resolved.geo_filter),
        "segment":  list(resolved.segment_filter),
        "fiscal":   fq.fiscal_quarter_label or fq.fiscal_year_label
                    or (f"{fq.quarter_labels[0]} to {fq.quarter_labels[-1]}" if fq.quarter_labels else None),
        "metric":   resolved.metric.name,
    }


def run(query: str, session_company=None, *, insight: bool = True) -> PipelineResponse | None:
    """
    Run the full pipeline for a single query.
    Returns PipelineResponse, or None if the user cancelled at clarification.
    """
    total = 7

    # ── S1: Extract ──────────────────────────────────────────────────────────
    step = _Step(1, total, "Extracting entities")
    with _quiet():
        extracted = s1_extract.extract(query)
    step.done(f"intent={extracted.intent.value}  "
              f"products={extracted.products_raw or '—'}  "
              f"geo={extracted.geo_raw or '—'}")
    _vprint("S1 Extracted", {
        "intent":    extracted.intent.value,
        "account":   extracted.account_raw or "—",
        "products":  extracted.products_raw or "—",
        "geo":       extracted.geo_raw or "—",
        "segment":   extracted.segment_raw or "—",
        "order_type": extracted.order_type_raw or "—",
        "metric":    extracted.metric_raw,
        "fiscal":    extracted.fiscal_raw or "—",
        "operator":  extracted.operator or "—",
        "limit":     extracted.limit_n or "—",
        "missing":   extracted.missing_critical or "none",
    })

    # ── S2: Resolve (6 tools in parallel) ───────────────────────────────────
    step = _Step(2, total, "Running 6 resolution tools")
    with _quiet():
        resolved_base = s2_resolve.resolve(extracted)
    note = (f"products={len(resolved_base.product_filter)}  "
            f"geo={resolved_base.geo_filter}  "
            f"company={len(resolved_base.company_matches)} match(es)")
    if resolved_base.ambiguities:
        step.warn(f"{note}  ambiguous: {resolved_base.ambiguities}")
    else:
        step.done(note)
    _vprint("S2 Resolved", {
        "product_filter":  [" › ".join(p.path) for p in resolved_base.product_filter] or "—",
        "geo_filter":      resolved_base.geo_filter or "—",
        "segment_filter":  resolved_base.segment_filter or "—",
        "order_type_filter": resolved_base.order_type_filter or "—",
        "fiscal":          str(resolved_base.fiscal.fiscal_quarter_label or resolved_base.fiscal.fiscal_year_label
                               or (f"{q[0]} → {q[-1]} ({len(q)} quarters)"
                                   if (q := resolved_base.fiscal.quarter_labels) else "—")),
        "metric":          f"{resolved_base.metric.name} → {resolved_base.metric.table}.{resolved_base.metric.col}",
        "company_matches": [f"{m.account_name} ({m.score:.2f})" for m in resolved_base.company_matches],
        "ambiguities":     resolved_base.ambiguities or "none",
    })

    # ── S3: Clarify + one-hop LLM re-run ────────────────────────────────────
    step = _Step(3, total, "Clarification gate")
    print()
    clarification = s3_clarify.clarify(resolved_base)

    if not clarification.answerable:
        step.fail(f"NOT ANSWERABLE: {clarification.not_answerable_reason}")
        return None

    if clarification.cancelled:
        step.fail("User cancelled")
        return None

    if clarification.addendum:
        if clarification.pinned_company or clarification.pinned_fiscal or clarification.pinned_products is not None:
            # Inject pinned values directly — skip S1+S2 re-run to prevent hallucinations.
            from pipeline.models import AccountFilter
            updates: dict = {}
            labels: list[str] = []

            if clarification.pinned_products is not None:
                updates["product_filter"] = s2_resolve._drop_ancestors(
                    list(resolved_base.product_filter) + clarification.pinned_products)
                updates["product_hierarchy_candidates"] = {}
                labels.append("product=" + (", ".join(" › ".join(p.path) for p in clarification.pinned_products)
                                            or "none"))

            if clarification.pinned_company:
                pc = clarification.pinned_company
                updates["account_filter"]    = AccountFilter(
                    account_raw  = pc.account_name,
                    account_id   = pc.account_id,
                    account_name = pc.account_name,
                )
                updates["company_matches"]   = [pc]
                updates["company_ambiguous"] = False
                labels.append(f"company='{pc.account_name}'")

            if clarification.pinned_fiscal:
                pf = clarification.pinned_fiscal
                updates["fiscal"]       = pf
                updates["fiscal_valid"] = True
                updates["fiscal_warning"] = None
                fq = pf.fiscal_quarter_label or pf.fiscal_year_label or \
                     (f"{pf.quarter_labels[0]}→{pf.quarter_labels[-1]}" if pf.quarter_labels else "all")
                labels.append(f"fiscal='{fq}'")

            updates["ambiguities"] = [
                a for a in resolved_base.ambiguities
                if not (clarification.pinned_company and a == "company")
                and not (clarification.pinned_fiscal  and a == "fiscal")
                and not (clarification.pinned_products is not None and a == "product_hierarchy")
            ]
            resolved = resolved_base.model_copy(update=updates)
            step.warn(f"one-hop inject → {', '.join(labels)} (no S1/S2 re-run)")
        else:
            # Non-company clarification (product, metric, geo): re-run S1+S2
            enriched_query = query + clarification.addendum
            step.warn(f"one-hop re-run → '{enriched_query[:60]}...'")

            step_hop1 = _Step(3, total, "  ↳ S1 re-extract (hop)")
            extracted2 = s1_extract.extract(enriched_query)
            step_hop1.done(f"intent={extracted2.intent.value}")

            step_hop2 = _Step(3, total, "  ↳ S2 re-resolve (hop)")
            resolved = s2_resolve.resolve(extracted2)
            step_hop2.done(f"products={[p.l1 for p in resolved.product_filter]}  geo={resolved.geo_filter}")

        # Re-classify after hop
        from pipeline.models import ResolvedEntities
        answerable2, reason2 = s3_clarify._classify(resolved)
        if not answerable2:
            step.fail(f"NOT ANSWERABLE after hop: {reason2}")
            print(f"\n  {_R}✗ NOT ANSWERABLE{_RS}  {reason2}\n")
            return None

        step.done("one-hop complete — ANSWERABLE")
    else:
        resolved = resolved_base
        step.done("no clarification needed — ANSWERABLE")

    # ── S4: Assemble enriched JSON + SQL context ─────────────────────────────
    step = _Step(4, total, "Assembling enriched context")
    import json as _json
    enriched, ctx = s4_context.build_context(resolved)
    step.done(f"table={ctx.primary_table}  "
              f"where={list(ctx.where_values.keys())}  "
              f"group_by={ctx.group_by}")
    _vprint("S4 EnrichedQuery", _json.loads(enriched.model_dump_json()))
    _vprint("S4 SQLContext", {
        "table":     ctx.primary_table,
        "join":      ctx.join_clause or "none",
        "where":     ctx.where_values,
        "group_by":  ctx.group_by or "none",
        "order_by":  ctx.order_by or "none",
        "limit":     ctx.limit,
    })

    # ── S5: Generate SQL ─────────────────────────────────────────────────────
    step = _Step(5, total, f"Generating SQL ({_D}ZLLAMA{_RS})")
    if _VERBOSE:
        gen = s5_generate.generate(ctx)
    else:
        with contextlib.redirect_stdout(io.StringIO()):  # S5 prints each attempt; the plan view replaces it
            gen = s5_generate.generate(ctx)
    if gen.source == "fallback":
        step.warn(f"fell back to skeleton after {gen.attempts} attempt(s)")
    else:
        step.done(f"attempt {gen.attempts}")
    _vprint("S5 Generated SQL", gen.sql)
    if gen.validation_errors:
        _vprint("S5 Validation Errors", gen.validation_errors)

    # ── S6: Execute (with one DB-error retry back through S5) ───────────────
    step = _Step(6, total, "Executing query")
    result = s6_execute.execute(gen.sql, limit=ctx.limit)
    if result.db_error and gen.source == "llm":
        step.warn(f"DB error — retrying S5 with error feedback: {result.db_error[:80]}")
        _vprint("S6 DB Error (retry)", {"error": result.db_error, "sql": gen.sql[:200]})
        with contextlib.redirect_stdout(io.StringIO()):
            gen = s5_generate.generate(
                ctx,
                db_error_feedback=result.db_error,
                db_failed_sql=gen.sql,
            )
        result = s6_execute.execute(gen.sql, limit=ctx.limit)

    if result.db_error:
        step.fail(result.db_error)
        _vprint("S6 DB Error", {"error": result.db_error, "sql": gen.sql[:200]})
    else:
        step.done(f"{result.row_count} rows  {result.elapsed_ms:.0f}ms")
        if result.rows:
            _vprint("S6 First Row Preview", result.rows[0])

    # ── S7: Insight + sanity ─────────────────────────────────────────────────
    step = _Step(7, total, "Generating insight")
    warnings = s7_respond.sanity_check(result, ctx)
    insight_text = s7_respond.generate_insight(result, query) if (insight and result.success) else ""
    chart    = s7_respond.auto_chart_type(result, ctx)
    step.done(f"chart={chart}  warnings={len(warnings)}")

    return PipelineResponse(
        question=query,
        context=ctx,
        generated=gen,
        result=result,
        sanity_warnings=warnings,
        insight=insight_text,
        chart_type=chart,
        entities=_entities(resolved),
    )


# ── Multi-part orchestration (S0 plan -> run each part -> merge) ─────────────

@dataclass
class PartOutcome:
    id:       str
    text:     str                          # the text that actually ran (placeholders bound)
    response: PipelineResponse | None = None
    error:    str | None = None


@dataclass
class MultiOutcome:
    plan:    DecompositionPlan
    parts:   list[PartOutcome] = field(default_factory=list)
    merged:  str = ""


_BIND_RE = re.compile(r"\{\{\s*(q\d+)\.account\s*\}\}")


class _Unbound(Exception):
    pass


def _bind(text: str, done: dict[str, PartOutcome]) -> str:
    """Fill `{{qN.account}}` with the first account of part N's real result row (never an LLM guess)."""
    def sub(m: re.Match) -> str:
        part = done.get(m.group(1))
        if part is None or part.response is None:
            raise _Unbound(f"{m.group(1)} did not produce a result to depend on")
        res = part.response.result
        col = account_column(res.columns)
        if not (col and res.rows and res.rows[0].get(col)):
            raise _Unbound(f"{m.group(1)} returned no account to carry forward")
        return str(res.rows[0][col])
    return _BIND_RE.sub(sub, text)


def _print_plan(plan: DecompositionPlan, show_json: bool) -> None:
    label = {"passthrough": "single question", "split": f"split into {len(plan.sub_queries)} parts",
             "followup": "follow-up resolved"}[plan.strategy]
    print(f"  {_B}S0 Plan{_RS}  {_D}{label}{_RS}")
    for n in plan.notes:
        print(f"    {_Y}↳ {n}{_RS}")
    if plan.strategy != "passthrough" or plan.notes:
        for w, wave in enumerate(s0_decompose.order(plan.sub_queries) or [plan.sub_queries], 1):
            tag = "independent, can run together" if len(wave) > 1 else "runs after the previous stage" if w > 1 else ""
            if len(plan.sub_queries) > 1:
                print(f"    {_D}stage {w}{f' — {tag}' if tag else ''}{_RS}")
            for sq in wave:
                dep = f"  {_D}(needs {', '.join(sq.depends_on)}){_RS}" if sq.depends_on else ""
                print(f"    {_C}{sq.id}{_RS}  {sq.text}{dep}")
    if show_json and plan.strategy != "passthrough":
        print(f"{_D}{plan.model_dump_json(indent=2)}{_RS}")


def run_multi(query: str, memory: SessionMemory | None = None, *, show_sql: bool = False,
              show_plan_json: bool = False, display: bool = True) -> MultiOutcome:
    """S0 -> run every sub-query through S1..S6 -> one merged answer. Saves each answered part to memory."""
    global _VERBOSE
    memory = memory if memory is not None else SessionMemory()
    plan = s0_decompose.plan(query, memory)
    if display:
        _print_plan(plan, show_plan_json)
    out = MultiOutcome(plan=plan)

    if plan.unresolved:
        for u in plan.unresolved:
            msg = f"Could not resolve {u}"
            out.parts.append(PartOutcome(id="q1", text=query, error=msg))
            if display:
                print(f"\n  {_R}✗ {msg}{_RS}")
        return out

    total = len(plan.sub_queries)
    single = total == 1
    done: dict[str, PartOutcome] = {}
    for i, sq in enumerate(plan.sub_queries, 1):
        part = PartOutcome(id=sq.id, text=sq.text)
        done[sq.id] = part
        out.parts.append(part)
        failed_dep = next((d for d in sq.depends_on if done[d].error), None)
        if failed_dep:
            part.error = f"skipped — it depends on {failed_dep}, which failed"
            continue
        try:
            part.text = _bind(sq.text, done)
        except _Unbound as e:
            part.error = f"skipped — {e}"
            continue

        if display and not single:
            print(f"\n  {_D}▶ running {sq.id}: {part.text}{_RS}")
        _VERBOSE = single and display
        try:
            part.response = run(part.text, insight=single and display)
        except EOFError:
            part.error = "needs clarification (no interactive input available)"
        except Exception as e:  # one broken part must not take the others down
            part.error = f"{e.__class__.__name__}: {str(e)[:120]}"
        finally:
            _VERBOSE = True
        if part.response is None and part.error is None:
            part.error = "not answerable or cancelled at clarification"

        if part.response is not None and part.response.result.success:
            memory.add(Turn(query=query, standalone=part.text, entities=part.response.entities,
                            columns=part.response.result.columns, rows=part.response.result.rows))

    if display:
        for i, p in enumerate(out.parts, 1):
            if p.response is not None and not single:
                s7_respond.display_part(p.response, i, total, p.text, show_sql=show_sql)
            elif p.response is not None:
                s7_respond.display(p.response, show_sql=show_sql)
            else:
                s7_respond.display_part_failure(i, total, p.text, p.error or "failed")
        if not single:
            out.merged = s7_respond.generate_merged_insight(
                query, [(p.text, p.response.result if p.response else None, p.error or "") for p in out.parts])
    return out


# ── Terminal REPL ─────────────────────────────────────────────────────────────

_BANNER = f"""
  {_B}╔{'═' * (_W - 2)}╗
  ║{'ARR Analytics  —  pop_db':^{_W - 2}}║
  ║{'data_arr + dim_account  |  type /help for commands':^{_W - 2}}║
  ╚{'═' * (_W - 2)}╝{_RS}
"""

_HELP = f"""
  {_B}Commands:{_RS}
    /sql       Toggle SQL display for the next result
    /plan      Toggle the S0 plan JSON for split questions
    /help      Show this message
    /quit      Exit
    <query>    Any natural language ARR question

  {_B}Example queries:{_RS}
    top 10 accounts by ARR in EMEA for FY 2026 Q1
    total ARR by product in Americas FY 2026
    ARR trend for Siemens by quarter in FY 2026
    compare EMEA vs Americas ARR in Q1 FY 2026
    what is Salesforce ARR in FY 2026 Q1
"""


def repl() -> None:
    print(_BANNER)
    print(f"  {_D}Loading product hierarchy…{_RS}", end="", flush=True)
    print(f"\r  {_D}Product hierarchy: {hierarchy.warm()} names loaded{_RS}      ")

    memory          = SessionMemory()
    show_sql        = False
    show_plan_json  = False
    logger          = SessionLogger()
    print(f"  {_D}Results logged to: {logger.path()}{_RS}")

    try:
        while True:
            try:
                query = input(f"\n  {_C}> {_RS}").strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n  {_D}Goodbye.{_RS}\n")
                break

            if not query:
                continue

            # Commands
            if query.lower() in ("/quit", "/exit", "quit", "exit", "q"):
                print(f"  {_D}Goodbye.{_RS}\n")
                break
            if query.lower() == "/help":
                print(_HELP)
                continue
            if query.lower() == "/sql":
                show_sql = not show_sql
                print(f"  {_D}SQL display: {'ON' if show_sql else 'OFF'}{_RS}")
                continue
            if USE_MEMORY and query.lower() == "/clear":
                memory.clear()
                print(f"  {_D}Session memory cleared.{_RS}")
                continue
            if query.lower() == "/plan":
                show_plan_json = not show_plan_json
                print(f"  {_D}Plan JSON: {'ON' if show_plan_json else 'OFF'}{_RS}")
                continue
            if USE_MEMORY and query.lower() == "/memory":
                for t in memory.prompt_context(6) or [{"question": "(empty)"}]:
                    print(f"  {_D}{t}{_RS}")
                continue

            if query.startswith("/"):
                print(f"  {_Y}Unknown command {query.split()[0]!r}{'' if USE_MEMORY else ' (follow-up memory is off in this demo)'}. "
                      f"Type /help.{_RS}")
                continue

            print()
            if not USE_MEMORY:
                memory.clear()
            outcome = run_multi(query, memory, show_sql=show_sql, show_plan_json=show_plan_json)
            for part in outcome.parts:
                if part.response is not None:
                    logger.log(part.response)
    finally:
        logger.close()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"\n  {_B}Query:{_RS} {query}\n")
        with SessionLogger() as logger:
            outcome = run_multi(query, SessionMemory(), show_sql=True, show_plan_json=True)
            for part in outcome.parts:
                if part.response is not None:
                    logger.log(part.response)
            print(f"\n  {_D}Logged → {logger.path()}{_RS}")
    else:
        repl()
