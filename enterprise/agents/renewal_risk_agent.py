"""Renewal Risk Agent — manages account renewal risk scores on data_renewal_risk."""
from __future__ import annotations

from typing import Any
from agents.base_agent import MetricAgent
from pipeline.models import Intent, MetricAgentRequest, SQLContext


class RenewalRiskAgent(MetricAgent):
    def __init__(self, metric_name: str = "RENEWAL_RISK"):
        super().__init__(metric_name)

    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        resolved = request.resolved
        where_values: dict[str, Any] = {}

        if resolved.fiscal and resolved.fiscal.fiscal_quarter_label:
            where_values["fiscal_quarter"] = resolved.fiscal.fiscal_quarter_label

        if resolved.geo_filter:
            where_values["cfy_geo"] = resolved.geo_filter.value

        if resolved.segment_filter:
            where_values["market_segment"] = resolved.segment_filter

        if resolved.account_filter:
            if resolved.account_filter.account_name:
                where_values["account_name"] = resolved.account_filter.account_name
            elif resolved.account_filter.account_id:
                where_values["account_id"] = resolved.account_filter.account_id

        group_by = ["account_id", "account_name"]
        order_by = "avg_risk_score DESC"

        return SQLContext(
            normalized_question=request.question,
            intent=resolved.extracted.intent,
            metric="renewal_risk_score",
            metric_name="RENEWAL_RISK",
            metric_variant="snapshot",
            metric_agg="AVG",
            primary_table="data_renewal_risk",
            join_clause="",
            schema_ddl=self.metric_def.schema_ddl(),
            where_values=where_values,
            group_by=group_by,
            order_by=order_by,
            limit=resolved.extracted.limit_n or 10,
        )

