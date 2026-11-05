"""Base Metric Agent — abstract class for all metric agents.

Flow:
  1. build_context(request) -> SQLContext (subclass schema knowledge)
  2. generate_sql(ctx) -> GeneratedSQL (Sonnet LLM + cache)
  3. execute(sql, ctx) -> QueryResult (asyncpg or CSV dry-run)
  4. sanity_check -> SanityWarnings
  5. generate_insight -> grounded narrative
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import logging

from core.settings import get_ai, get_db
from core.mdl_registry import get_registry, MetricDefinition
from pipeline.models import (
    MetricAgentRequest,
    MetricAgentResponse,
    SQLContext,
    GeneratedSQL,
    QueryResult,
    Intent,
    ChartType,
)
from sql.generator import generate as generate_sql
from sql.executor import execute as execute_sql
from response.sanity import sanity_check
from response.insight import generate_insight
from core.log import step, ok, warn, sql_block
from sql.builder import _sql_literal, _where_parts

logger = logging.getLogger(__name__)


class MetricAgent(ABC):
    def __init__(self, metric_name: str):
        self.metric_name = metric_name
        registry = get_registry()
        self.metric_def: MetricDefinition = registry.get(
            metric_name,
            MetricDefinition(
                name=metric_name,
                display_name=metric_name,
                description=metric_name,
                table="data_arr",
                value_column="arr",
                aggregation="SUM",
                variant="snapshot",
                agent_class_path="agents.base_agent.MetricAgent",
            )
        )
        self.ai = get_ai()
        self.db = get_db()

    @abstractmethod
    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        """Construct the SQLContext tailored to this metric's table and logic."""
        ...

    @staticmethod
    def _product_where(resolved, prefix: str = "", max_level: int = 5) -> dict:
        """WHERE entries for every resolved product (OR semantics across products), at any level."""
        filters = resolved.product_filters or ([resolved.product_filter] if resolved.product_filter else [])
        if not filters:
            return {}

        def col(n: int) -> str:
            return f"{prefix}product_l{n}"

        paths = list(dict.fromkeys(tuple(f.path[:max_level]) for f in filters if f.path))
        if not paths:
            return {}
        if all(len(p) == 1 for p in paths):
            vals = [p[0] for p in paths]
            return {col(1): vals[0]} if len(vals) == 1 else {f"{col(1)}__in": vals}
        if len(paths) == 1:
            return {col(i): v for i, v in enumerate(paths[0], 1)}

        clauses = [
            "(" + " AND ".join(f"{col(i)} = {_sql_literal(v)}" for i, v in enumerate(p, 1)) + ")"
            for p in paths
        ]
        return {"__raw_product__": "(" + " OR ".join(clauses) + ")"}

    @staticmethod
    def _company_where(af) -> dict:
        """Company filter on data_arr: end user (end_user_id) or, when matched by parent name, the parent."""
        if not af or not (af.account_id or af.account_name):
            return {}
        if af.multiple:
            ids, levels = af.account_ids, (af.account_levels or ["end_user"] * len(af.account_ids))
        else:
            ids, levels = ([af.account_id], [af.level]) if af.account_id else ([], [])
        end_users = [i for i, l in zip(ids, levels) if l != "parent"]
        parents = [i for i, l in zip(ids, levels) if l == "parent"]

        def one_or_in(col: str, vals: list) -> dict:
            return {col: vals[0]} if len(vals) == 1 else {f"{col}__in": vals}

        if end_users and not parents:
            return one_or_in("end_user_id", end_users)
        if parents and not end_users:
            return one_or_in("end_user_parent_id", parents)
        if end_users and parents:
            eu = ", ".join(_sql_literal(i) for i in end_users)
            pa = ", ".join(_sql_literal(i) for i in parents)
            return {"__raw_company__": f"(end_user_id IN ({eu}) OR end_user_parent_id IN ({pa}))"}
        return {"end_user_name": af.account_name}

    @classmethod
    def _company_account_filter(cls, af) -> dict:
        """The same company as a filter on tables keyed by account_id only (e.g. data_quantity)."""
        cond = cls._company_where(af)
        if not cond:
            return {}
        if "end_user_name" in cond:
            return {"__raw_company__": f"account_id IN (SELECT DISTINCT account_id FROM data_arr WHERE end_user_name = {_sql_literal(cond['end_user_name'])})"}
        inner = " AND ".join(_where_parts(cond))
        return {"__raw_company__": f"account_id IN (SELECT DISTINCT account_id FROM data_arr WHERE {inner})"}

    @staticmethod
    def _multi_product_group(resolved, prefix: str = "") -> list[str]:
        """Product GROUP BY: an explicit 'all L<n> products' breakdown, else several products with no account pinned."""
        if resolved.product_level:
            return [f"{prefix}product_l{resolved.product_level}"]
        filters = resolved.product_filters
        if len(filters) < 2 or (resolved.account_filter and resolved.account_filter.account_id):
            return []
        return [f"{prefix}product_l{max(f.deepest_level for f in filters) or 1}"]

    def _auto_chart(self, result: QueryResult, ctx: SQLContext) -> ChartType:
        """Determines best visual presentation based on columns and intent."""
        cols = [c.lower() for c in result.columns]
        if ctx.intent == Intent.TREND or any("quarter" in c or "month" in c or "date" in c for c in cols):
            return "line"
        if len(result.rows) == 1 and len(result.columns) <= 2:
            return "stat_card"
        if any("name" in c or "account" in c or "product" in c or "geo" in c for c in cols):
            return "bar"
        return "table"

    async def run(self, request: MetricAgentRequest) -> MetricAgentResponse:
        """Orchestrates end-to-end execution for this metric."""
        step(f"Agent [{self.metric_name}]", "building SQL context…")
        ctx = self.build_context(request)
        if ctx.blocked_reason:
            warn(f"Agent [{self.metric_name}] not available", ctx.blocked_reason)
            return MetricAgentResponse(
                metric_name=self.metric_name,
                display_name=self.metric_def.display_name,
                sql=GeneratedSQL(sql="-- not available", source="error", attempts=0, validation_errors=[ctx.blocked_reason]),
                result=QueryResult(sql="", rows=[], columns=[], row_count=0, elapsed_ms=0.0, db_error=None, success=True),
                insight=ctx.blocked_reason,
                sanity_warnings=[],
                chart_type="table",
            )

        step(f"Agent [{self.metric_name}]", "generating SQL…")
        gen = await generate_sql(ctx, self.metric_def)
        ok(f"Agent [{self.metric_name}] SQL ({gen.source})", f"attempt={gen.attempts}")
        sql_block(gen.sql)

        step(f"Agent [{self.metric_name}]", "executing query…")
        result = await execute_sql(gen.sql, ctx)

        # One retry if DB reports execution error
        if result.db_error and gen.source == "llm":
            warn(f"Agent [{self.metric_name}] DB error — retrying", result.db_error[:120])
            gen = await generate_sql(
                ctx,
                self.metric_def,
                db_error_feedback=result.db_error,
                db_failed_sql=gen.sql,
            )
            sql_block(gen.sql)
            result = await execute_sql(gen.sql, ctx)

        if result.success:
            ok(f"Agent [{self.metric_name}] query done", f"rows={result.row_count}  elapsed={result.elapsed_ms}ms")
        else:
            warn(f"Agent [{self.metric_name}] query failed", result.db_error or "unknown error")

        warnings = sanity_check(result, ctx)
        if warnings:
            warn(f"Agent [{self.metric_name}] sanity", "  ".join(f"{w.code}: {w.message}" for w in warnings))

        step(f"Agent [{self.metric_name}]", "generating insight…")
        insight_text = await generate_insight(result, request.question) if result.success else ""

        return MetricAgentResponse(
            metric_name=self.metric_name,
            display_name=self.metric_def.display_name,
            sql=gen,
            result=result,
            insight=insight_text,
            sanity_warnings=warnings,
            chart_type=self._auto_chart(result, ctx),
        )

