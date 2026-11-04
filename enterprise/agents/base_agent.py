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
        ctx = self.build_context(request)
        gen = await generate_sql(ctx, self.metric_def)
        result = await execute_sql(gen.sql, ctx)

        # One retry if DB reports execution error
        if result.db_error and gen.source == "llm":
            logger.info(f"DB execution error on attempt 1. Retrying S5 with error feedback: {result.db_error[:100]}")
            gen = await generate_sql(
                ctx,
                self.metric_def,
                db_error_feedback=result.db_error,
                db_failed_sql=gen.sql,
            )
            result = await execute_sql(gen.sql, ctx)

        warnings = sanity_check(result, ctx)
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

