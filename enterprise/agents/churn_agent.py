"""Churn & Downsell Agent — manages ARR attrition and downsell queries."""
from __future__ import annotations

from typing import Any
from agents.base_agent import MetricAgent
from pipeline.models import Intent, MetricAgentRequest, SQLContext


class ChurnAgent(MetricAgent):
    def __init__(self, metric_name: str = "CHURN"):
        super().__init__(metric_name)

    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        resolved = request.resolved
        where_values: dict[str, Any] = {"aggregation_level": "Level L3"}

        if resolved.fiscal:
            if resolved.fiscal.fiscal_quarter_label:
                where_values["fiscal_quarter"] = resolved.fiscal.fiscal_quarter_label
            elif resolved.fiscal.quarter_labels:
                where_values["fiscal_quarter__in"] = resolved.fiscal.quarter_labels

        if resolved.geo_filter:
            where_values["cfy_geo"] = resolved.geo_filter.value

        if resolved.product_filter and resolved.product_filter.l1:
            where_values["product_l1"] = resolved.product_filter.l1

        if resolved.account_filter:
            if resolved.account_filter.account_name:
                where_values["end_user_parent_name"] = resolved.account_filter.account_name
            elif resolved.account_filter.account_id:
                where_values["end_user_parent_id"] = resolved.account_filter.account_id

        intent = resolved.extracted.intent
        group_by = ["end_user_parent_id", "end_user_parent_name"]
        order_by = "total_downsell ASC"  # Most negative first

        if intent == Intent.TREND:
            group_by = ["fiscal_quarter"]
            order_by = "fiscal_quarter ASC"

        return SQLContext(
            normalized_question=request.question,
            intent=intent,
            metric="downsell",
            metric_name="CHURN",
            metric_variant="downsell",
            metric_agg="SUM",
            primary_table="data_inc_arr",
            join_clause="",
            schema_ddl=self.metric_def.schema_ddl(),
            where_values=where_values,
            group_by=group_by,
            order_by=order_by,
            limit=resolved.extracted.limit_n or 10,
        )

