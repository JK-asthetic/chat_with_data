"""Churn Reason Agent — categorizes customer attrition reasons on data_churn_reason."""
from __future__ import annotations

from typing import Any
from agents.base_agent import MetricAgent
from pipeline.models import Intent, MetricAgentRequest, SQLContext


class ChurnReasonAgent(MetricAgent):
    def __init__(self, metric_name: str = "CHURN_REASON"):
        super().__init__(metric_name)

    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        resolved = request.resolved
        where_values: dict[str, Any] = {}

        if resolved.fiscal and resolved.fiscal.fiscal_quarter_label:
            where_values["fiscal_quarter"] = resolved.fiscal.fiscal_quarter_label

        if resolved.account_filter:
            if resolved.account_filter.account_name:
                where_values["account_name"] = resolved.account_filter.account_name
            elif resolved.account_filter.account_id:
                where_values["account_id"] = resolved.account_filter.account_id

        if resolved.geo_filter:
            where_values["cfy_geo"] = resolved.geo_filter.value

        group_by = ["churn_reason"]
        order_by = "total_churn_amount DESC"

        return SQLContext(
            normalized_question=request.question,
            intent=resolved.extracted.intent,
            metric="churn_amount",
            metric_name="CHURN_REASON",
            metric_variant="snapshot",
            metric_agg="SUM",
            primary_table="data_churn_reason",
            join_clause="",
            schema_ddl=self.metric_def.schema_ddl(),
            where_values=where_values,
            group_by=group_by,
            order_by=order_by,
            limit=resolved.extracted.limit_n or 10,
        )

