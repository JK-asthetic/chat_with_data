"""NACV Target Agent — manages planning targets and quotas by product."""
from __future__ import annotations

from typing import Any
from agents.base_agent import MetricAgent
from pipeline.models import Intent, MetricAgentRequest, SQLContext


class NACVTargetAgent(MetricAgent):
    def __init__(self, metric_name: str = "NACV"):
        super().__init__(metric_name)

    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        resolved = request.resolved
        where_values: dict[str, Any] = {}

        if resolved.fiscal:
            if resolved.fiscal.fiscal_quarter_label:
                where_values["fiscal_quarter"] = resolved.fiscal.fiscal_quarter_label
            elif resolved.fiscal.quarter_labels:
                where_values["fiscal_quarter__in"] = resolved.fiscal.quarter_labels

        if resolved.product_filter:
            if resolved.product_filter.l1:
                where_values["fy27_product_l1"] = resolved.product_filter.l1
            if resolved.product_filter.l2:
                where_values["fy27_product_l2"] = resolved.product_filter.l2

        group_by = ["fy27_product_l1", "fy27_product_l2", "fiscal_quarter"]
        order_by = "total_target DESC"

        return SQLContext(
            normalized_question=request.question,
            intent=resolved.extracted.intent,
            metric="target",
            metric_name="NACV",
            metric_variant="target",
            metric_agg="SUM",
            primary_table="data_nacv_target",
            join_clause="",
            schema_ddl=self.metric_def.schema_ddl(),
            where_values=where_values,
            group_by=group_by,
            order_by=order_by,
            limit=resolved.extracted.limit_n or 15,
        )

