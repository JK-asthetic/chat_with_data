"""ACV & NNACV Agent — handles deal-level contract value bookings."""
from __future__ import annotations

from typing import Any
from agents.base_agent import MetricAgent
from pipeline.models import Intent, MetricAgentRequest, SQLContext


class ACVAgent(MetricAgent):
    def __init__(self, metric_name: str = "ACV"):
        super().__init__(metric_name)

    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        resolved = request.resolved
        where_values: dict[str, Any] = {}

        # NNACV automatically excludes renewals
        if self.metric_name.upper() == "NNACV":
            where_values["carve_split_type__not_in"] = ["Renewal"]

        # 1. Fiscal filters
        if resolved.fiscal:
            if resolved.fiscal.fiscal_quarter_label:
                where_values["fiscal_quarter"] = resolved.fiscal.fiscal_quarter_label
            elif resolved.fiscal.fiscal_year_label:
                where_values["fiscal_year"] = resolved.fiscal.fiscal_year_label
            elif resolved.fiscal.quarter_labels:
                where_values["fiscal_quarter__in"] = resolved.fiscal.quarter_labels

        # 2. Geo filters — note: data_acv uses plain `geo`
        if resolved.geo_filter:
            where_values["geo"] = resolved.geo_filter.value

        # 3. Product filters
        if resolved.product_filter:
            if resolved.product_filter.l1:
                where_values["product_l1"] = resolved.product_filter.l1
            if resolved.product_filter.l2:
                where_values["product_l2"] = resolved.product_filter.l2

        # 4. Account filter
        if resolved.account_filter:
            if resolved.account_filter.multiple:
                where_values["account_name__in"] = resolved.account_filter.multiple
            elif resolved.account_filter.account_name:
                where_values["account_name"] = resolved.account_filter.account_name
            elif resolved.account_filter.account_id:
                where_values["account_id"] = resolved.account_filter.account_id

        # 5. Order type -> carve_split_type
        if resolved.order_type_filter:
            where_values["carve_split_type"] = resolved.order_type_filter

        intent = resolved.extracted.intent
        group_by = ["account_id", "account_name"]
        order_by = "total_acv DESC"

        if intent == Intent.TREND:
            group_by = ["fiscal_quarter"]
            order_by = "fiscal_quarter ASC"
        elif intent == Intent.COMPARE:
            group_by = ["geo"] if resolved.geo_filter else ["product_l1"]

        return SQLContext(
            normalized_question=request.question,
            intent=intent,
            metric="adjusted_acv",
            metric_name=self.metric_name,
            metric_variant=self.metric_def.variant,
            metric_agg=self.metric_def.aggregation,
            primary_table="data_acv",
            join_clause="",
            schema_ddl=self.metric_def.schema_ddl(),
            where_values=where_values,
            group_by=group_by,
            order_by=order_by,
            limit=resolved.extracted.limit_n or 10,
        )

