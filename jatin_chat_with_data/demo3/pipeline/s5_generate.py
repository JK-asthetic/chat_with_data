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

# ── Prompt builder ────────────────────────────────────────────────────────────

_GLOBAL_EXAMPLE = """\
-- Example (top accounts with rank + percentage share):
SELECT
    end_user_name,
    SUM(arr)                                                          AS total_arr,
    RANK() OVER (ORDER BY SUM(arr) DESC)                             AS rank,
    ROUND(100.0 * SUM(arr) / SUM(SUM(arr)) OVER (), 1)              AS pct_of_total
FROM data_arr
WHERE fiscal_year = 'FY 2026'
  AND fiscal_quarter = 'FY 2026 Q1'
GROUP BY end_user_name
ORDER BY total_arr DESC
LIMIT 10;

-- Example (product breakdown with account count + avg ARR):
SELECT
    product_l1,
    SUM(arr)                                                          AS total_arr,
    COUNT(DISTINCT end_user_name)                                     AS account_count,
    ROUND(SUM(arr) / NULLIF(COUNT(DISTINCT end_user_name), 0), 0)   AS avg_arr_per_account,
    ROUND(100.0 * SUM(arr) / SUM(SUM(arr)) OVER (), 1)              AS pct_of_total
FROM data_arr
WHERE end_user_parent_geo = 'EMEA'
  AND fiscal_year = 'FY 2026'
  AND fiscal_quarter = 'FY 2026 Q1'
GROUP BY product_l1
ORDER BY total_arr DESC
LIMIT 10;

-- Example (QoQ trend with delta):
WITH periods AS (
    SELECT
        fiscal_quarter,
        end_user_name,
        SUM(arr) AS total_arr
    FROM data_arr
    WHERE fiscal_year IN ('FY 2025', 'FY 2026')
    GROUP BY fiscal_quarter, end_user_name
)
SELECT
    fiscal_quarter,
    end_user_name,
    total_arr,
    LAG(total_arr) OVER (PARTITION BY end_user_name ORDER BY fiscal_quarter) AS prev_arr,
    total_arr - LAG(total_arr) OVER (PARTITION BY end_user_name ORDER BY fiscal_quarter) AS delta_arr,
    ROUND(100.0 * (total_arr - LAG(total_arr) OVER (PARTITION BY end_user_name ORDER BY fiscal_quarter))
          / NULLIF(LAG(total_arr) OVER (PARTITION BY end_user_name ORDER BY fiscal_quarter), 0), 1) AS delta_pct
FROM periods
ORDER BY fiscal_quarter, total_arr DESC
LIMIT 10;"""


def _sql_literal(v: object) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _where_parts(where_values: dict) -> list[str]:
    """SQL conditions (one string each) for the pre-resolved WHERE values."""
    parts = []
    for col, val in where_values.items():
        if col == "__or__":  # product nodes at different depths: one AND-group per node
            groups = [" AND ".join(f"{c} = {_sql_literal(v)}" for c, v in g.items()) for g in val]
            parts.append("(" + " OR ".join(f"({g})" for g in groups) + ")")
        elif col.endswith("__in"):
            parts.append(f"{col[:-4]} IN ({', '.join(_sql_literal(v) for v in val)})")
        else:
            parts.append(f"{col} = {_sql_literal(val)}")
    return parts


def _format_where(where_values: dict) -> str:
    """Format WHERE clause values as SQL conditions for the prompt."""
    if not where_values:
        return "  -- no filters (return all rows)"
    return "\n".join(f"  {p}" for p in _where_parts(where_values))


def _enrichment_hints(ctx: SQLContext) -> str:
    """Intent-specific SELECT enrichment guidance.

    Tells the LLM what additional columns to include for richer insights.
    Enrichments go only in SELECT / window expressions — never in WHERE.
    """
    intent = ctx.intent.value if ctx.intent else "AGGREGATE"
    metric = ctx.metric
    agg    = ctx.metric_agg
    expr   = f"{agg}({metric})"

    common = f"""\
- Alias the metric clearly: `{expr} AS total_{metric}`
- When grouping by a dimension (product, geo, segment), add:
    COUNT(DISTINCT end_user_name) AS account_count
    ROUND({expr} / NULLIF(COUNT(DISTINCT end_user_name), 0), 0) AS avg_{metric}_per_account
- Add percentage share for every multi-row result:
    ROUND(100.0 * {expr} / SUM({expr}) OVER (), 1) AS pct_of_total"""

    by_intent = {
        "RANK": f"""\
- Add RANK() OVER (ORDER BY {expr} DESC) AS rank in SELECT
- Add pct_of_total share column
- ORDER BY metric DESC so rank 1 = highest""",

        "DELTA": f"""\
- Use LAG() or a CTE to compute period-over-period change
- Add: delta_{metric} = current_arr - previous_arr
       delta_pct      = ROUND(100.0 * delta / NULLIF(previous, 0), 1)
- If only one period is in the WHERE, omit the delta (it cannot be computed without a second period)""",

        "TREND": f"""\
- Include fiscal_quarter in SELECT and GROUP BY to show trend over time
- Add delta and delta_pct using LAG() OVER (PARTITION BY <group> ORDER BY fiscal_quarter)
- ORDER BY fiscal_quarter ASC, then metric DESC within each period""",

        "COMPARE": f"""\
- Keep both sides of the comparison as rows — do NOT pivot into columns
- Include the split dimension (fiscal_quarter or the grouping column) as a SELECT column
- Add a delta column between the two sides where the GROUP BY allows it""",

        "RISK": f"""\
- Add a risk_flag: CASE WHEN {expr} < LAG({expr}) OVER (...) THEN 'Declining' ELSE 'Stable' END
- Include delta_pct to quantify severity
- ORDER BY metric ASC to surface the worst performers first""",

        "LOOKUP": f"""\
- Show all relevant breakdown columns from the GROUP BY
- Add pct_of_total for share context when multiple rows are returned
- If a single account is the subject, add product_l1 to GROUP BY for a product breakdown""",

        "AGGREGATE": f"""\
- Add pct_of_total share column
- Add account_count when the GROUP BY is a dimension other than end_user_name""",
    }

    specific = by_intent.get(intent, by_intent["AGGREGATE"])
    return f"""### Insight Enrichment — make the output analytical, not just a raw total
Intent detected: {intent}

{common}

{specific}

Rules for enrichment:
- Add columns only in SELECT / window functions. NEVER add filters to WHERE.
- If a computation needs a second period not present in WHERE (e.g. for a delta),
  use a wider CTE that STILL respects all locked filters — do not inject extra literals.
- NULLIF every denominator to prevent division-by-zero.
- ROUND percentages to 1 decimal; ROUND large ARR amounts to 0 decimal places.
- Do not join extra tables or look up values not in the GROUP BY."""


def build_prompt(ctx: SQLContext, error_feedback: str | None = None, failed_sql: str | None = None) -> str:
    """Build the full SQL-generation prompt from SQLContext; a retry also gets the failed SQL and its errors."""
    where_block      = _format_where(ctx.where_values)
    join_block       = f"-- JOIN: {ctx.join_clause}" if ctx.join_clause else "-- No JOIN needed"
    group_block      = ", ".join(ctx.group_by) if ctx.group_by else "-- no GROUP BY (single aggregate)"
    order_block      = ctx.order_by or "-- no ORDER BY"
    enrichment_block = _enrichment_hints(ctx)

    error_block = ""
    if error_feedback:
        sql_block = f"Your previous SQL:\n{failed_sql}\n\n" if failed_sql else ""
        error_block = f"""
### Previous attempt failed — fix this error:
{sql_block}Errors:
{error_feedback}

"""

    return f"""### Task
Write a rich, insight-ready Postgres SQL query to answer: {ctx.normalized_question}

### Database Schema
{ctx.schema_ddl}

### Rules
{ctx.rules}

### CRITICAL — Pre-resolved WHERE clause (USE EXACTLY THESE, NO OTHERS)
The WHERE conditions below are the COMPLETE, already-validated filter set produced by the
entity extractor. DO NOT add, infer, or guess any extra filters — no company names, no
account names, no product values, no geo or segment values — beyond what is listed here.
If a field is absent from the list, it MUST NOT appear in the SQL WHERE clause.
When in doubt, omit the filter rather than assuming.

Table:     {ctx.primary_table}
{join_block}
WHERE (exhaustive — add nothing else):
{where_block}
GROUP BY:  {group_block}
ORDER BY:  {order_block}
LIMIT:     {ctx.limit}

{enrichment_block}

### Reference Examples
{_GLOBAL_EXAMPLE}
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

_DEAD_TABLES  = {"dim_product_hierarchy"}
_VALID_TABLES = {"data_arr", "dim_account"}
_FORBIDDEN    = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|COPY)\b",
    re.IGNORECASE,
)
_GEO_COL_RE   = re.compile(r"\bdata_arr\b.*?\bgeo\b(?!\s*=\s*'[^']*')", re.IGNORECASE | re.DOTALL)


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
                errors.append(f"V3 Dead table '{name}' — not in scope")
            elif name not in _VALID_TABLES:
                errors.append(f"V2 Unknown table '{name}' — not in scope (data_arr, dim_account)")
    except Exception:
        pass

    # V4: geo column guard for data_arr
    # Catches: data_arr.geo, d.geo, a.geo, bare 'geo =' near data_arr context
    if "DATA_ARR" in sql_up:
        # Check for short .geo references that aren't part of end_user_parent_geo
        if re.search(r"\b(?<!\w)geo\s*=", sql_up) and "END_USER_PARENT_GEO" not in sql_up:
            errors.append(
                "V4 Wrong geo column — data_arr uses 'end_user_parent_geo', not 'geo' or 'cfy_geo'"
            )

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
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
        allowed = {c.lower() for g in ctx.where_values.get("__or__", []) for c in g}
        allowed |= {(k[:-4] if k.endswith("__in") else k).lower() for k in ctx.where_values if k != "__or__"}
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
    # Qualify the metric column with table name when a JOIN is present
    # to avoid "column reference 'arr' is ambiguous" (dim_account also has arr)
    tbl_prefix    = "data_arr." if ctx.join_clause else ""
    metric_expr   = f"SUM({tbl_prefix}arr) AS total_arr"

    # SELECT must exactly mirror GROUP BY to avoid Postgres aggregate errors
    group_cols  = ctx.group_by or ["end_user_name"]
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
    errors: list[str] = ([f"DB execution error: {db_error_feedback}"] if db_error_feedback else [])
    failed_sql: str | None = db_failed_sql  # the previous attempt's SQL, sent back with its errors

    for attempt in range(1, cfg.MAX_SQL_RETRIES + 1):
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
                                "You are a business analytics SQL expert. "
                                "Write rich, insight-ready Postgres SQL that goes beyond a bare SUM — "
                                "include ranks, shares, deltas, and counts where they add value. "
                                "Output only valid Postgres SQL. No markdown, no explanation, no inline comments."
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
            if choice.get("finish_reason") == "length":  # cut off mid-query: a retry with the same budget fails the same way
                errors = [f"SQL was cut off at {cfg.SQL_MAX_TOKENS} tokens — answer with a shorter query"]
                failed_sql = None
                continue
            raw_sql = choice["message"]["content"].strip()
            sql = _clean(raw_sql)
        except Exception as e:
            errors = [f"ZLLAMA error: {e}"]
            failed_sql = None  # the call failed, so there is no SQL to show the model
            continue

        sql        = qualify_join_columns(sql, ctx)
        sql        = pin_group_by_aliases(sql)
        errors     = validate(sql, ctx)
        failed_sql = sql if errors else None

        print(f"\n    ↳ Attempt {attempt} SQL:\n      {sql[:300]}")
        if errors:
            print(f"    ↳ Validation errors: {errors}")
        else:
            print(f"    ↳ Validation: PASS  (via ZLLAMA {cfg.ZLLAMA_SQL_MODEL})")

        if not errors:
            return GeneratedSQL(sql=sql, source="llm", attempts=attempt)

    # All attempts failed → deterministic fallback
    skeleton = _build_skeleton(ctx)
    return GeneratedSQL(
        sql=skeleton,
        source="fallback",
        attempts=cfg.MAX_SQL_RETRIES,
        validation_errors=errors,
    )

