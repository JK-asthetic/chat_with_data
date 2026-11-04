"""Quantity Agent — manages seat and license quantity queries on data_quantity."""
from __future__ import annotations

from typing import Any
from agents.base_agent import MetricAgent
from pipeline.models import Intent, MetricAgentRequest, SQLContext


class QuantityAgent(MetricAgent):
    def __init__(self, metric_name: str = "QTY"):
        super().__init__(metric_name)

    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        resolved = request.resolved
        # Always M3 end-of-quarter snapshot
        where_values: dict[str, Any] = {"fiscal_month_m_of_quarter": "M3"}

        if resolved.fiscal and resolved.fiscal.fiscal_quarter_label:
            where_values["fiscal_quarter"] = resolved.fiscal.fiscal_quarter_label

        if resolved.product_filter and resolved.product_filter.l1:
            where_values["product_l1"] = resolved.product_filter.l1

        if resolved.account_filter:
            if resolved.account_filter.account_name:
                where_values["account_name"] = resolved.account_filter.account_name
            elif resolved.account_filter.account_id:
                where_values["account_id"] = resolved.account_filter.account_id

        group_by = ["account_id", "account_name", "product_l1"]
        order_by = "total_qty DESC"

        return SQLContext(
            normalized_question=request.question,
            intent=resolved.extracted.intent,
            metric="product_l1_qty",
            metric_name="QTY",
            metric_variant="snapshot",
            metric_agg="SUM",
            primary_table="data_quantity",
            join_clause="",
            schema_ddl=self.metric_def.schema_ddl(),
            where_values=where_values,
            group_by=group_by,
            order_by=order_by,
            limit=resolved.extracted.limit_n or 10,
        )

