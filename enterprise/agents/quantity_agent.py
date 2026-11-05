"""Quantity Agent — seat / license quantity on data_quantity.

Quantity is a stock like ARR, but data_quantity is MONTHLY (fiscal_month = first day of the month).
A single month is always filtered (never summed across months without GROUP BY fiscal_month):
  * a quarter means its LAST month (FY 2027 Q1 -> fiscal_month = '2026-10-01');
  * a month the user names is used as is;
  * a month/quarter that has no data yet (ongoing / upcoming) falls back to the previous quarter's last month.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any, Optional

from agents.base_agent import MetricAgent
from core import fiscal_calendar as cal
from core.db import query_one
from core.log import warn
from core.table_profiles import PROFILES, table_filters
from pipeline.models import Fiscal, Intent, MetricAgentRequest, SQLContext


@lru_cache(maxsize=2)
def _latest_month(day: str) -> Optional[date]:
    row = query_one("SELECT MAX(fiscal_month) AS m FROM data_quantity WHERE fiscal_month <= CURRENT_DATE")
    return row["m"] if row and row["m"] else None


class QuantityAgent(MetricAgent):
    def __init__(self, metric_name: str = "QTY"):
        super().__init__(metric_name)

    @staticmethod
    def _clamp(month: date, latest: Optional[date], notes: list[str]) -> date:
        """No data for that month yet -> the previous quarter's last month, until data exists."""
        if not latest:
            return month
        original = month
        while month > latest:
            month = cal.last_month_start(cal.prev_quarter(cal.quarter_of(month)))
        if month != original:
            notes.append(f"no quantity data for {original:%b %Y} yet (ongoing/upcoming) — using {month:%b %Y}")
        return month

    def _period_where(self, fiscal: Optional[Fiscal], intent: Intent) -> tuple[dict[str, Any], bool, list[str]]:
        notes: list[str] = []
        latest = _latest_month(date.today().isoformat())
        periods = [p for p in (fiscal, fiscal.compare_to if fiscal else None) if p]

        # last closed quarter = the latest quarter whose last month already has data
        last_closed: Optional[cal.Quarter] = None
        if latest:
            last_closed = cal.quarter_of(latest)
            if cal.last_month_start(last_closed) > latest:
                last_closed = cal.prev_quarter(last_closed)

        months: list[date] = []
        for p in periods:
            if p.month_start:
                months.append(self._clamp(date.fromisoformat(p.month_start), latest, notes))
            elif p.fiscal_quarter_label and cal.parse_quarter(p.fiscal_quarter_label):
                months.append(self._clamp(cal.last_month_start(cal.parse_quarter(p.fiscal_quarter_label)), latest, notes))
            elif p.quarter_labels:
                for q in cal.clamp_range(p.quarter_labels, last_closed):
                    pq = cal.parse_quarter(q)
                    if pq:
                        months.append(self._clamp(cal.last_month_start(pq), latest, notes))
            elif p.fiscal_year_label:
                months.append(self._clamp(cal.last_month_start((int(p.fiscal_year_label.split()[1]), 4)), latest, notes))

        if not months:
            if intent == Intent.TREND:
                return ({"fiscal_month__lte": latest.isoformat()} if latest else {}), True, notes
            if latest:
                months = [self._clamp(cal.last_month_start(cal.quarter_of(latest)), latest, notes)]

        months = sorted(dict.fromkeys(months))
        if len(months) > 1:
            return {"fiscal_month__in": [m.isoformat() for m in months]}, True, notes
        if months:
            m = months[0]
            return {"fiscal_quarter": cal.label(cal.quarter_of(m)), "fiscal_month": m.isoformat()}, False, notes
        return {}, False, notes

    @staticmethod
    def _arr_quarters(where_values: dict[str, Any]) -> list[str]:
        """Quarter(s) of the resolved month(s), for mapping geo/segment through data_arr."""
        if "fiscal_quarter" in where_values:
            return [where_values["fiscal_quarter"]]
        months = where_values.get("fiscal_month__in") or []
        qs = list(dict.fromkeys(cal.label(cal.quarter_of(date.fromisoformat(m))) for m in months))
        return qs or [cal.label(cal.last_complete_quarter())]

    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        resolved = request.resolved
        intent = resolved.extracted.intent

        where_values, multi_month, notes = self._period_where(resolved.fiscal, intent)
        for n in notes:
            warn("Period mapping", n)

        # every filter (geo / segment / product / company) through the table profile; geo and segment have no
        # column here, so they are applied through the account's snapshot attributes in data_arr
        arr_quarters = self._arr_quarters(where_values)
        filters, fnotes, blocked = table_filters(PROFILES["data_quantity"], resolved, arr_quarters)
        if blocked:
            return SQLContext(normalized_question=request.question, intent=intent, metric="product_l1_qty",
                              metric_name="QTY", primary_table="data_quantity", blocked_reason=f"Quantity: {blocked}.")
        where_values.update(filters)
        for n in fnotes:
            warn("Period / cut", n)
        af = resolved.account_filter
        pfilters = resolved.product_filters or ([resolved.product_filter] if resolved.product_filter else [])
        qty_level = min(5, resolved.product_level or max([f.deepest_level for f in pfilters], default=1) or 1)
        qty_col = f"product_l{qty_level}_qty"                      # level-matched column — never mix levels

        # Default shape: product-wise (like the monthly product view) or company-wise when a company is pinned.
        group_by = ["fiscal_month"]
        product_group = self._multi_product_group(resolved) or ([f"product_l{qty_level}"] if pfilters else [])
        if intent == Intent.RANK:
            group_by += ["account_id", "account_name"]
        elif af and af.account_id:
            group_by += ["account_id", "account_name"] + product_group
        else:
            group_by += product_group or ["product_l1"]

        account_level = "account_id" in group_by
        order_by = f"fiscal_month ASC, total_{qty_col} DESC" if multi_month else f"total_{qty_col} DESC"
        limit_n = resolved.extracted.limit_n or 10
        limit = limit_n if account_level else max(limit_n, 100)

        return SQLContext(
            normalized_question=request.question,
            intent=intent,
            metric=qty_col,
            metric_name="QTY",
            metric_variant="snapshot",
            metric_agg="SUM",
            primary_table="data_quantity",
            join_clause="",
            schema_ddl=self.metric_def.schema_ddl(),
            where_values=where_values,
            group_by=group_by,
            order_by=order_by,
            limit=limit,
        )
