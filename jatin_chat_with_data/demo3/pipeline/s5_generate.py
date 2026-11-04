"""
Stage 5 — SQL Generation (ZLLAMA LLM + Validation + Retry Loop).

Flow:
  SQLContext JSON
    → build_prompt()       ← injects minimal schema + resolved WHERE values
    → ZLLAMA (Haiku)       ← temperature=0, structured prompt
    → validate()           ← 7-point validator (sqlglot + schema checks)
    → retry if FAIL        ← inject error message, max MAX_SQL_RETRIES attempts
    → fallback skeleton    ← deterministic SQL if all attempts fail
    → GeneratedSQL
"""
from __future__ import annotations

import re

import requests
import sqlglot
import sqlglot.errors

from core.config import get_settings
from pipeline.models import GeneratedSQL, SQLContext
from pipeline import nl_sql_memory
from pipeline import phase_errors as pe

# ── Prompt builder ────────────────────────────────────────────────────────────

# (global examples removed — each metric section has one focused example)


# ── Shared infrastructure rules (injected into every metric prompt) ───────────

_SHARED_INFRA = """
### Infrastructure Rules (apply to every query)
- ALWAYS include LIMIT
- fiscal_year format: 'FY 2026' — NEVER 'FY26' or bare '2026'
- fiscal_quarter format: 'FY 2026 Q1' — NEVER 'Q1FY26' or bare 'Q1'
- WHERE values are pre-resolved and exhaustive — add NOTHING beyond what is listed.
- COUNT(DISTINCT account_id) for account counts.
- NULLIF every denominator (division-by-zero prevention).
- Return ONLY valid Postgres SQL — no markdown, no comments, no explanation.
- Use IN (...) for multiple values — never multiple separate WHERE conditions.
""".strip()


# ── Metric-specific prompt bodies — one per table family ───────────────────────

_ARR_SNAPSHOT_PROMPT = """
### Metric: ARR — data_arr
Example:
SELECT account_id,
       end_user_name AS account_name,
       SUM(arr)      AS total_arr
FROM data_arr
WHERE fiscal_quarter = 'FY 2027 Q1'
  AND fiscal_month_end_date = '2026-10-31'
GROUP BY account_id, end_user_name
ORDER BY total_arr DESC
LIMIT 10;

Rules:
- NEVER use account_name — use end_user_name AS account_name.
- NEVER use product+level — use product_l1, product_l2, etc.
- NEVER use geo/area/region — use cfy_geo, cfy_area, cfy_region.
- fiscal_month_end_date is pre-set in WHERE for snapshot; do NOT remove it.
""".strip()


_ACV_PROMPT = """
### Metric: ACV — data_acv
Example:
SELECT account_id,
       account_name,
       SUM(adjusted_acv) AS total_acv
FROM data_acv
WHERE fiscal_quarter = 'FY 2027 Q1'
  AND carve_split_type = 'NEW_CUST'
GROUP BY account_id, account_name
ORDER BY total_acv DESC
LIMIT 20;

Rules:
- Use SUM(adjusted_acv) AS total_acv.
- NEVER use cfy_geo/cfy_area/cfy_region — use `geo` column.
- NEVER use product+level — use product_l1, product_l2, etc.
- carve_split_type filter from WHERE must be used EXACTLY as given.
- Do NOT add is_latest — this table has no such column.
""".strip()


_INCR_ARR_PROMPT = """
### Metric: Incremental ARR — data_inc_arr
Example:
SELECT end_user_parent_id,
       end_user_parent_name,
       SUM(arr_change) AS total_incr_arr
FROM data_inc_arr
WHERE fiscal_quarter = 'FY 2027 Q1'
  AND aggregation_level = 'Level L3'
GROUP BY end_user_parent_id, end_user_parent_name
ORDER BY total_incr_arr DESC
LIMIT 20;

Rules:
- NEVER use account_id/account_name — use end_user_parent_id and end_user_parent_name.
- aggregation_level = 'Level L3' MUST remain in WHERE.
- NEVER use product+level — use product_l1, product_l2.
""".strip()


_CHURN_PROMPT = """
### Metric: Churn / Downsell — data_inc_arr
Example:
SELECT end_user_parent_id,
       end_user_parent_name,
       SUM(downsell) AS total_downsell
FROM data_inc_arr
WHERE fiscal_quarter = 'FY 2027 Q1'
  AND aggregation_level = 'Level L3'
GROUP BY end_user_parent_id, end_user_parent_name
HAVING SUM(downsell) < 0
ORDER BY total_downsell ASC
LIMIT 20;

Rules:
- NEVER use account_id — use end_user_parent_id and end_user_parent_name.
- aggregation_level = 'Level L3' MUST remain in WHERE.
- ORDER BY total_downsell ASC (most negative = most churn first).
- Add HAVING SUM(downsell) < 0 to show only churned accounts.
""".strip()


_QTY_PROMPT = """
### Metric: Quantity (seats/licenses) — data_quantity
Example:
SELECT account_id,
       account_name,
       product_l1,
       SUM(product_l1_qty) AS total_qty
FROM data_quantity
WHERE fiscal_quarter = 'FY 2027 Q1'
  AND fiscal_month_m_of_quarter = 'M3'
GROUP BY account_id, account_name, product_l1
ORDER BY total_qty DESC
LIMIT 20;

Rules:
- fiscal_month_m_of_quarter = 'M3' MUST remain in WHERE.
- NEVER add geo filters — this table has no geo column.
- Use product_l1_qty (L1), product_l2_qty (L2) as appropriate.
""".strip()


_NACV_TARGET_PROMPT = """
### Metric: NACV Target — data_nacv_target
Example:
SELECT fy27_product_l1,
       fy27_product_l2,
       fiscal_quarter,
       SUM(target) AS total_target
FROM data_nacv_target
WHERE fiscal_quarter = 'FY 2027 Q1'
GROUP BY fy27_product_l1, fy27_product_l2, fiscal_quarter
ORDER BY total_target DESC
LIMIT 20;

Rules:
- Use fy27_product_l1, fy27_product_l2, fy27_product_l3 (NOT product_l1).
- No geo, segment, or account filters — this table has none.
- target_type filter from WHERE must be used EXACTLY as given.
""".strip()


# ── Metric prompt selector — routes by primary_table ──────────────────────────

def _metric_prompt(ctx: "SQLContext") -> str:  # noqa: F821
    """Return the table-family-specific prompt body for this query."""
    table   = ctx.primary_table.lower()
    name    = ctx.metric_name.upper()
    variant = ctx.metric_variant.lower()

    if table == "data_acv":
        return _ACV_PROMPT
    if table == "data_inc_arr":
        if name == "CHURN" or variant == "downsell":
            return _CHURN_PROMPT
        return _INCR_ARR_PROMPT
    if table == "data_nacv_target":
        return _NACV_TARGET_PROMPT
    if table == "data_quantity":
        return _QTY_PROMPT
    # data_arr — all ARR queries
    return _ARR_SNAPSHOT_PROMPT


def _sql_literal(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return "'" + str(v).replace("'", "''") + "'"


def _where_parts(where_values: dict) -> list[str]:
    """SQL conditions (one string each) for the pre-resolved WHERE values."""
    parts = []
    for col, val in where_values.items():
        if col.startswith("_"):          # internal hint keys — skip
            continue
        if col == "__or__":              # product nodes at different depths
            groups = [" AND ".join(f"{c} = {_sql_literal(v)}" for c, v in g.items()) for g in val]
            parts.append("(" + " OR ".join(f"({g})" for g in groups) + ")")
        elif col.endswith("__in"):
            parts.append(f"{col[:-4]} IN ({', '.join(_sql_literal(v) for v in val)})")
        elif col.endswith("__not_in"):
            parts.append(f"{col[:-8]} NOT IN ({', '.join(_sql_literal(v) for v in val)})")
        elif col.endswith("__gte"):
            parts.append(f"{col[:-5]} >= {_sql_literal(val)}")
        elif col.endswith("__lte"):
            parts.append(f"{col[:-5]} <= {_sql_literal(val)}")
        else:
            parts.append(f"{col} = {_sql_literal(val)}")
    return parts


def _format_where(where_values: dict) -> str:
    """Format WHERE clause values as SQL conditions for the prompt."""
    if not where_values:
        return "  -- no filters (return all rows)"
    return "\n".join(f"  {p}" for p in _where_parts(where_values))


def build_prompt(ctx: SQLContext, error_feedback: str | None = None, failed_sql: str | None = None) -> str:
    """Build the SQL-generation prompt; selects a metric-specific body for focused reasoning."""
    where_block = _format_where(ctx.where_values)
    join_block  = f"-- JOIN: {ctx.join_clause}" if ctx.join_clause else "-- No JOIN needed"
    group_block = ", ".join(ctx.group_by) if ctx.group_by else "-- no GROUP BY (single aggregate)"
    order_block = ctx.order_by or "-- no ORDER BY"
    metric_body = _metric_prompt(ctx)

    few_shot_block = nl_sql_memory.get_memory().few_shot_prompt(ctx.normalized_question)

    error_block = ""
    if error_feedback:
        sql_block = f"Your previous SQL:\n{failed_sql}\n\n" if failed_sql else ""
        error_block = f"""
### Previous attempt failed — fix this error:
{sql_block}Errors:
{error_feedback}

"""

    return f"""### Task
Write Postgres SQL to answer: {ctx.normalized_question}

### Database Schema
{ctx.schema_ddl}

{_SHARED_INFRA}

{metric_body}

{few_shot_block}### WHERE (pre-resolved — use EXACTLY these, add NOTHING else)
Table:    {ctx.primary_table}
{join_block}
WHERE:
{where_block}
GROUP BY: {group_block}
ORDER BY: {order_block}
LIMIT:    {ctx.limit}
{error_block}### SQL
"""


# ── SQL cleaner ───────────────────────────────────────────────────────────────

def _clean(raw: str) -> str:
    """Strip markdown fences, comment prefixes, and extra prose."""
    sql = raw.strip()
    if "```" in sql:
        parts = sql.split("```")
        for p in parts:
            p = p.strip().lstrip("sql").strip()
            if p.upper().startswith(("SELECT", "WITH")):
                sql = p
                break
    if sql.lower().startswith("sql\n"):
        sql = sql[4:].strip()
    # Strip leading comment lines (SQLCoder sometimes prefixes with "-- SELECT ...")
    lines = sql.split("\n")
    while lines and lines[0].strip().startswith("--"):
        lines.pop(0)
    sql = "\n".join(lines).strip()
    # Keep first statement only
    if ";" in sql:
        sql = sql.split(";")[0].strip() + ";"
    return sql.strip()


# ── Validator ─────────────────────────────────────────────────────────────────

_DEAD_TABLES  = {"dim_product_hierarchy", "t6_arr_contract", "t6_acv_contract"}
_VALID_TABLES = {
    "data_arr", "data_acv", "data_inc_arr", "data_nacv_target",
    "data_quantity", "dim_account",
}
_FORBIDDEN    = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|COPY)\b",
    re.IGNORECASE,
)



def qualify_join_columns(sql: str, ctx: SQLContext) -> str:
    """When a JOIN is present, qualify unambiguous metric columns with the primary table name.

    `SUM(arr)` becomes `SUM(data_arr.arr)` so Postgres doesn't error on
    "column reference 'arr' is ambiguous" when dim_account is joined in.
    Uses sqlglot AST so aliases like `total_arr` are untouched.
    """
    if not ctx.join_clause:
        return sql
    metric_col = ctx.metric.lower()
    primary    = ctx.primary_table.lower()
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
        for col in tree.find_all(sqlglot.exp.Column):
            if col.name.lower() == metric_col and not col.table:
                col.set("table", sqlglot.exp.Identifier(this=primary))
        return tree.sql(dialect="postgres")
    except Exception:
        return sql


def pin_group_by_aliases(sql: str) -> str:
    """Rewrite `GROUP BY <alias>` to its select position when the alias names a computed expression.

    Postgres binds a bare GROUP BY name to an input column first, and only falls back to the select alias when
    no such column exists. data_arr has columns the model never sees (product_category, ...), so
    `CASE ... END AS product_category ... GROUP BY product_category` fails with "must appear in the GROUP BY".
    A positional GROUP BY is correct either way. Returns `sql` untouched when nothing needs rewriting.
    """
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.ParseError:
        return sql
    group = tree.args.get("group") if isinstance(tree, sqlglot.exp.Select) else None
    if not group:
        return sql
    computed = {e.alias.lower(): i for i, e in enumerate(tree.expressions, 1)
                if isinstance(e, sqlglot.exp.Alias) and not isinstance(e.this, sqlglot.exp.Column)}
    changed = False
    for i, g in enumerate(group.expressions):
        if isinstance(g, sqlglot.exp.Column) and not g.table and g.name.lower() in computed:
            group.expressions[i] = sqlglot.exp.Literal.number(computed[g.name.lower()])
            changed = True
    return tree.sql(dialect="postgres") if changed else sql


def validate(sql: str, ctx: SQLContext) -> list[str]:
    """
    Returns list of validation error strings (empty = valid).
    V1 syntax, V2 table registry, V3 dead tables,
    V4 geo column, V5 fiscal format, V6 mutation guard, V7 LIMIT.
    """
    errors: list[str] = []

    # V1: sqlglot parse
    try:
        sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.ParseError as e:
        errors.append(f"V1 Syntax error: {str(e)[:200]}")
        return errors  # no point checking further

    sql_up = sql.upper()

    # V2 + V3: table checks
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
        ctes = {c.alias.lower() for c in parsed.find_all(sqlglot.exp.CTE)}  # WITH names are not tables
        for t in parsed.find_all(sqlglot.exp.Table):
            name = t.name.lower()
            if name in ctes:
                continue
            if name in _DEAD_TABLES:
                errors.append(
                    f"V3 Retired table '{name}' — use data_arr (ARR) or data_acv (ACV) instead"
                )
            elif name not in _VALID_TABLES:
                errors.append(
                    f"V2 Unknown table '{name}' — valid tables: "
                    "data_arr, data_acv, data_inc_arr, data_nacv_target, data_quantity, dim_account"
                )
    except Exception:
        pass

    # V4: table-specific column guards
    if "DATA_ARR" in sql_up:
        # data_arr uses end_user_name (not account_name), cfy_geo (not geo), product_l1 (not product+level)
        if re.search(r"\bACCOUNT_NAME\b", sql_up) and "DATA_ACV" not in sql_up:
            errors.append("V4 data_arr has no 'account_name' column — use 'end_user_name'")
        if re.search(r"\b(IS_LATEST|LEVEL)\b", sql_up):
            errors.append("V4 data_arr has no 'is_latest' or 'level' column — do NOT filter by them")
        if re.search(r"\bFROM DATA_ARR\b.*?\bWHERE.*?\bGEO\s*=", sql_up, re.DOTALL):
            errors.append("V4 data_arr uses cfy_geo not geo — use cfy_geo/cfy_area/cfy_region")
    if "DATA_ACV" in sql_up:
        # data_acv uses geo (not cfy_geo), product_l1 (not product+level)
        if re.search(r"\bCFY_GEO\b|\bCFY_AREA\b|\bCFY_REGION\b", sql_up):
            errors.append("V4 data_acv uses plain `geo` column, not cfy_geo/cfy_area/cfy_region")
        if re.search(r"\bIS_LATEST\b", sql_up):
            errors.append("V4 data_acv has no 'is_latest' column — do NOT filter by it")
        if re.search(r"\bPRODUCT\s*=", sql_up) and re.search(r"\bLEVEL\s*=", sql_up):
            errors.append("V4 data_acv has no product+level hierarchy — use product_l1, product_l2 flat columns")
    if "DATA_INC_ARR" in sql_up:
        if re.search(r"\bACCOUNT_ID\s*=", sql_up) or re.search(r"\bACCOUNT_NAME\b", sql_up):
            errors.append("V4 data_inc_arr is keyed on end_user_parent_id, not account_id/account_name")
        if "AGGREGATION_LEVEL" not in sql_up:
            errors.append("V4 data_inc_arr requires aggregation_level = 'Level L3' in WHERE")
    if "DATA_QUANTITY" in sql_up:
        if "FISCAL_MONTH_M_OF_QUARTER" not in sql_up:
            errors.append("V4 data_quantity requires fiscal_month_m_of_quarter = 'M3' in WHERE")

    # V5: fiscal format guard
    if re.search(r"=\s*'FY\d{2}'", sql, re.IGNORECASE):
        errors.append("V5 Wrong fiscal_year format — use 'FY 2026' not 'FY26'")
    if re.search(r"=\s*'Q[1-4]FY\d{2}'", sql, re.IGNORECASE):
        errors.append("V5 Wrong fiscal_quarter format — use 'FY 2026 Q1' not 'Q1FY26'")
    if re.search(r"fiscal_quarter\s*=\s*'Q[1-4]'", sql, re.IGNORECASE):
        errors.append("V5 Wrong fiscal_quarter format — use 'FY 2026 Q1' not bare 'Q1'")

    # V6: mutation guard
    if _FORBIDDEN.search(sql):
        errors.append("V6 Mutation statement detected — only SELECT is allowed")

    # V7: LIMIT guard
    if "LIMIT" not in sql_up:
        errors.append("V7 Missing LIMIT clause")

    # V8: no extra WHERE columns beyond pre-resolved set
    # Columns used structurally (self-join infrastructure, IS NOT NULL guards) are always allowed.
    _V8_STRUCTURAL = {
        "account_id", "account_name", "end_user_name", "end_user_parent_id",
        "end_user_parent_name", "contract_details_number",
    }
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
        def _base_col(k: str) -> str:
            for suffix in ("__not_in", "__in", "__gte", "__lte"):
                if k.endswith(suffix):
                    return k[: -len(suffix)]
            return k

        allowed = {c.lower() for g in ctx.where_values.get("__or__", []) for c in g}
        allowed |= {
            _base_col(k).lower()
            for k in ctx.where_values
            if k != "__or__" and not k.startswith("_")
        }
        allowed |= _V8_STRUCTURAL
        where = parsed.find(sqlglot.exp.Where)
        if where:
            for node in where.find_all(sqlglot.exp.EQ, sqlglot.exp.In):
                col = node.find(sqlglot.exp.Column)
                if col and col.name.lower() not in allowed:
                    errors.append(
                        f"V8 Extra WHERE filter on '{col.name}' — not in pre-resolved set {sorted(allowed)}"
                    )
    except Exception:
        pass

    return errors


# ── Fallback skeleton ─────────────────────────────────────────────────────────

def _build_skeleton(ctx: SQLContext) -> str:
    """
    Deterministic SQL skeleton — used when all SQLCoder attempts fail.
    Always syntactically correct because we build it from validated parts.
    """
    tbl_prefix  = f"{ctx.primary_table}." if ctx.join_clause else ""
    metric_col  = ctx.metric  # already resolved (arr / adjusted_acv / arr_change / etc.)
    alias_col   = metric_col.replace("adjusted_", "total_").replace("product_l1_", "total_")
    if alias_col == metric_col:
        alias_col = f"total_{metric_col}"
    metric_expr = f"SUM({tbl_prefix}{metric_col}) AS {alias_col}"

    # SELECT must exactly mirror GROUP BY to avoid Postgres aggregate errors
    group_cols  = ctx.group_by or ["account_id", "account_name"]
    select_cols = list(group_cols) + [metric_expr]

    where_parts = _where_parts(ctx.where_values)

    lines = [f"SELECT {', '.join(select_cols)}"]
    lines.append(f"FROM {ctx.primary_table}")
    if ctx.join_clause:
        lines.append(ctx.join_clause)
    if where_parts:
        lines.append("WHERE " + "\n  AND ".join(where_parts))
    lines.append(f"GROUP BY {', '.join(group_cols)}")
    if ctx.order_by:
        lines.append(f"ORDER BY {ctx.order_by}")
    lines.append(f"LIMIT {ctx.limit};")

    return "\n".join(lines)


# ── Public entry point ────────────────────────────────────────────────────────

def generate(ctx: SQLContext, db_error_feedback: str | None = None, db_failed_sql: str | None = None) -> GeneratedSQL:
    """
    Stage 5: SQL generation + validation + retry loop.

    db_error_feedback: a Postgres execution error from a previous S6 run.
      When provided, the first prompt already carries that error so the model
      can fix the SQL without burning an extra validation-only attempt.
    """
    cfg     = get_settings()
    mem     = nl_sql_memory.get_memory()

    # Seed with DB-level error if provided (comes from S6 retry)
    last_err: pe.PipelineError | None = (
        pe.s6_error(db_error_feedback, db_failed_sql) if db_error_feedback else None
    )
    errors: list[str] = ([f"DB execution error: {db_error_feedback}"] if db_error_feedback else [])
    failed_sql: str | None = db_failed_sql

    for attempt in range(1, cfg.MAX_SQL_RETRIES + 1):
        # Use structured retry hint when available (phase_errors); fall back to raw list
        if last_err and errors:
            error_feedback: str | None = pe.format_retry_hint(last_err) + "\n" + "\n".join(errors)
        else:
            error_feedback = "\n".join(errors) if errors else None

        prompt = build_prompt(ctx, error_feedback=error_feedback, failed_sql=failed_sql)

        try:
            base = cfg.ZLLAMA_BASE_URL.rstrip("/")
            resp = requests.post(
                f"{base}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg.ZLLAMA_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       cfg.ZLLAMA_SQL_MODEL,
                    "temperature": 0,
                    "max_tokens":  cfg.SQL_MAX_TOKENS,
                    "messages": [
                        {
                            "role":    "system",
                            "content": (
                                "You are a Postgres SQL expert. "
                                "Write correct, concise SQL that answers the question. "
                                "Follow the rules in the prompt exactly. "
                                "Output only valid Postgres SQL — no markdown, no explanation, no inline comments."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=(5, 30),
            )
            resp.raise_for_status()
            body = resp.text
            if not body.strip():
                raise ValueError("ZLLAMA returned empty body")
            choice = resp.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                msg = f"SQL was cut off at {cfg.SQL_MAX_TOKENS} tokens — answer with a shorter query"
                errors = [msg]
                last_err = pe.s5_error(pe.VALIDATOR_FAIL, msg, attempt=attempt)
                failed_sql = None
                continue
            raw_sql = choice["message"]["content"].strip()
            sql = _clean(raw_sql)
        except Exception as e:
            msg = f"ZLLAMA error: {e}"
            errors = [msg]
            last_err = pe.s5_error(pe.VALIDATOR_FAIL, msg, attempt=attempt)
            failed_sql = None
            continue

        sql        = qualify_join_columns(sql, ctx)
        sql        = pin_group_by_aliases(sql)
        val_errors = validate(sql, ctx)
        failed_sql = sql if val_errors else None

        print(f"\n    ↳ Attempt {attempt} SQL:\n      {sql[:300]}")
        if val_errors:
            errors = val_errors
            # Tag the error type for smarter retry hint
            first = val_errors[0]
            if "V1 Syntax" in first:
                last_err = pe.s5_error(pe.SYNTAX_ERROR, first, sql, attempt)
            elif "V2 Unknown table" in first or "V3 Dead table" in first:
                last_err = pe.s5_error(pe.FORBIDDEN_TABLE, first, sql, attempt)
            else:
                last_err = pe.s5_error(pe.VALIDATOR_FAIL, first, sql, attempt)
            print(f"    ↳ Validation errors: {val_errors}")
        else:
            print(f"    ↳ Validation: PASS  (via ZLLAMA {cfg.ZLLAMA_SQL_MODEL})")
            intent_val = ctx.intent.value if ctx.intent else "AGGREGATE"
            mem.add(ctx.normalized_question, sql, metric=ctx.metric_name, intent=intent_val)
            return GeneratedSQL(sql=sql, source="llm", attempts=attempt)

    # All attempts failed → deterministic fallback
    skeleton = _build_skeleton(ctx)
    return GeneratedSQL(
        sql=skeleton,
        source="fallback",
        attempts=cfg.MAX_SQL_RETRIES,
        validation_errors=errors,
    )

