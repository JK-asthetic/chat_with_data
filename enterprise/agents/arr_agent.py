"""ARR Snapshot Agent — manages Annual Recurring Revenue queries on data_arr."""
from __future__ import annotations

from typing import Any
from agents.base_agent import MetricAgent
from pipeline.models import Intent, MetricAgentRequest, SQLContext


class ARRAgent(MetricAgent):
    def __init__(self, metric_name: str = "ARR"):
        super().__init__(metric_name)

    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        resolved = request.resolved
        where_values: dict[str, Any] = {}

        # 1. Fiscal filters
        if resolved.fiscal:
            if resolved.fiscal.fiscal_quarter_label:
                where_values["fiscal_quarter"] = resolved.fiscal.fiscal_quarter_label
            elif resolved.fiscal.fiscal_year_label:
                where_values["fiscal_year"] = resolved.fiscal.fiscal_year_label
            elif resolved.fiscal.quarter_labels:
                where_values["fiscal_quarter__in"] = resolved.fiscal.quarter_labels

        # 2. Geo filters (cfy_geo / cfy_area / cfy_region)
        if resolved.geo_detail_filter:
            where_values[resolved.geo_detail_filter.col] = resolved.geo_detail_filter.value
        elif resolved.geo_filter:
            where_values["cfy_geo"] = resolved.geo_filter.value

        # 3. Product filters
        if resolved.product_filter:
            if resolved.product_filter.l1:
                where_values["product_l1"] = resolved.product_filter.l1
            if resolved.product_filter.l2:
                where_values["product_l2"] = resolved.product_filter.l2

        # 4. Account filter
        join_clause = ""
        if resolved.account_filter:
            if resolved.account_filter.multiple:
                where_values["end_user_name__in"] = resolved.account_filter.multiple
            elif resolved.account_filter.account_name:
                where_values["end_user_name"] = resolved.account_filter.account_name
            elif resolved.account_filter.account_id:
                where_values["account_id"] = resolved.account_filter.account_id

        # 5. Segment and order_type
        if resolved.segment_filter:
            where_values["market_segment"] = resolved.segment_filter
        if resolved.order_type_filter:
            where_values["mrr_order_type"] = resolved.order_type_filter

        # 6. Group by & Order by
        intent = resolved.extracted.intent
        group_by = []
        order_by = "total_arr DESC"

        if intent == Intent.TREND:
            group_by = ["fiscal_quarter"]
            order_by = "fiscal_quarter ASC"
        elif intent == Intent.LOOKUP:
            group_by = ["account_id", "end_user_name"]
        elif intent == Intent.RANK:
            group_by = ["account_id", "end_user_name"]
            order_by = "total_arr DESC"
        elif intent == Intent.COMPARE:
            group_by = ["cfy_geo"] if resolved.geo_filter else ["product_l1"]
        else:
            group_by = ["account_id", "end_user_name"]

        return SQLContext(
            normalized_question=request.question,
            intent=intent,
            metric="arr",
            metric_name="ARR",
            metric_variant="snapshot",
            metric_agg=self.metric_def.aggregation,
            primary_table="data_arr",
            join_clause=join_clause,
            schema_ddl=self.metric_def.schema_ddl(),
            where_values=where_values,
            group_by=group_by,
            order_by=order_by,
            limit=resolved.extracted.limit_n or 10,
        )

