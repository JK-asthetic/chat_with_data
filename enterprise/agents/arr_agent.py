"""ARR Snapshot Agent — Annual Recurring Revenue on data_arr.

ARR is a stock and data_arr holds ONE snapshot per fiscal quarter, labelled with the quarter's last
month ('FY 2027 Q1 OCT'). So:
  * a quarter / year / month all resolve to a quarter snapshot; several quarters are grouped by
    fiscal_quarter (never summed together);
  * a quarter that is ongoing or upcoming has no closed snapshot -> the last closed one is used (noted);
  * renewals are found on the PREVIOUS snapshot: "renewing in Q2 FY27" = rows of the Q1 FY27 snapshot
    whose contract end_date falls inside Q2 FY27.
"""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from typing import Any, Optional

from agents.base_agent import MetricAgent, requested_cut
from core import fiscal_calendar as cal
from core.db import query_one
from core.log import warn
from pipeline.models import Fiscal, Intent, MetricAgentRequest, SQLContext

_GEO_COL = {"geo": "cfy_geo", "area": "cfy_area", "region": "cfy_region"}
_NAME_EXPR = "(ARRAY_AGG(end_user_name ORDER BY arr DESC))[1] AS account_name"

_RENEW_WORD = re.compile(r"\brenew\w*", re.I)
_RENEW_DISPLAY = re.compile(r"\brenewal\s+(?:quarter|date|month|period|cycle)s?\b", re.I)
_RENEW_WINDOW = re.compile(
    r"\brenew(?:ing|als?|ed|s)?\s+(?:in|during|for|due|by|between|within)\b"
    r"|\b(?:due|up)\s+for\s+renewal\b|\brenewals?\s+(?:in|for|of)\b|\b(?:q[1-4]|fy)\s?'?\d*\s+renewals?\b",
    re.I,
)


def _renewal_mode(question: str) -> Optional[str]:
    """'window' = ARR renewing inside a period; 'display' = just show the renewal quarter; None = not a renewal question."""
    if not _RENEW_WORD.search(question or ""):
        return None
    if _RENEW_WINDOW.search(question):
        return "window"
    return "display" if _RENEW_DISPLAY.search(question) else None


@lru_cache(maxsize=64)
def _last_quarter(day: str, fy: Optional[str]) -> Optional[str]:
    """Latest fiscal_quarter whose snapshot is on/before today (optionally inside one fiscal year)."""
    sql = "SELECT fiscal_quarter FROM data_arr WHERE fiscal_month_end_date <= CURRENT_DATE"
    params = None
    if fy:
        sql += " AND fiscal_year = %(fy)s"
        params = {"fy": fy}
    sql += " ORDER BY fiscal_month_end_date DESC LIMIT 1"
    row = query_one(sql, params)
    return row["fiscal_quarter"] if row else None


@lru_cache(maxsize=2)
def _last_snapshot_date(day: str) -> Optional[str]:
    row = query_one("SELECT MAX(fiscal_month_end_date) AS d FROM data_arr WHERE fiscal_month_end_date <= CURRENT_DATE")
    return row["d"].isoformat() if row and row["d"] else None


class ARRAgent(MetricAgent):
    def __init__(self, metric_name: str = "ARR"):
        super().__init__(metric_name)

    @staticmethod
    def _snapshot(q: cal.Quarter, last: Optional[cal.Quarter], notes: list[str]) -> cal.Quarter:
        """An ongoing/upcoming quarter has no closed snapshot: use the last closed one."""
        if last and q > last:
            notes.append(f"{cal.label(q)} has no closed ARR snapshot yet (ongoing/upcoming) — using {cal.label(last)}")
            return last
        return q

    def _renewal_window(self, fiscal: Optional[Fiscal], last: Optional[cal.Quarter], notes: list[str]) -> dict[str, Any]:
        """ARR renewing in the asked period = previous snapshot + contract end_date inside the period."""
        if fiscal and fiscal.month_start:
            ms = date.fromisoformat(fiscal.month_start)
            first, start, end = cal.quarter_of(ms), ms, cal.month_end(ms)
        elif fiscal and fiscal.quarter_labels and all(cal.parse_quarter(q) for q in fiscal.quarter_labels):
            qs = [cal.parse_quarter(q) for q in fiscal.quarter_labels]
            first, start, end = qs[0], cal.quarter_start(qs[0]), cal.quarter_end(qs[-1])
        elif fiscal and fiscal.fiscal_quarter_label and cal.parse_quarter(fiscal.fiscal_quarter_label):
            first = cal.parse_quarter(fiscal.fiscal_quarter_label)
            start, end = cal.quarter_start(first), cal.quarter_end(first)
        elif fiscal and fiscal.fiscal_year_label:
            fy = int(fiscal.fiscal_year_label.split()[1])
            first, start, end = (fy, 1), cal.quarter_start((fy, 1)), cal.quarter_end((fy, 4))
        else:
            first = cal.next_quarter(last) if last else cal.quarter_of(date.today())
            start, end = cal.quarter_start(first), cal.quarter_end(first)
            notes.append(f"no period given — showing ARR renewing in the upcoming quarter {cal.label(first)}")
        snap = self._snapshot(cal.prev_quarter(first), last, notes)
        notes.append(f"renewals {start} .. {end}: snapshot {cal.label(snap)} filtered on contract end_date")
        return {"fiscal_quarter": cal.label(snap), "end_date__gte": start.isoformat(), "end_date__lte": end.isoformat()}

    def _period_where(self, fiscal: Optional[Fiscal], intent: Intent, question: str) -> tuple[dict[str, Any], bool, list[str]]:
        """Returns (where entries, multi_quarter, notes to show the user)."""
        today = date.today().isoformat()
        notes: list[str] = []
        last_label = _last_quarter(today, None)
        last = cal.parse_quarter(last_label) if last_label else None

        if _renewal_mode(question) == "window":
            return self._renewal_window(fiscal, last, notes), False, notes

        periods = [p for p in (fiscal, fiscal.compare_to if fiscal else None) if p]
        quarters: list[str] = []
        years: list[str] = []
        named_month: Optional[date] = None
        for p in periods:
            if p.month_start:
                named_month = named_month or date.fromisoformat(p.month_start)
                quarters.append(cal.label(cal.quarter_of(date.fromisoformat(p.month_start))))
            elif p.fiscal_quarter_label:
                quarters.append(p.fiscal_quarter_label)
            elif p.quarter_labels:
                quarters.extend(cal.clamp_range(p.quarter_labels, last))
            elif p.fiscal_year_label:
                years.append(p.fiscal_year_label)

        # Trend with no explicit quarters: the quarters of the year if one was given, else the trailing 8 quarters
        if intent == Intent.TREND and not quarters:
            where: dict[str, Any] = {}
            if len(years) == 1:
                where["fiscal_year"] = years[0]
                snap_date = _last_snapshot_date(today)
                if snap_date:
                    where["fiscal_month_end_date__lte"] = snap_date
            elif last:
                trail = [cal.label(x) for x in cal.trailing(last, 8)]
                notes.append(f"no period named — trailing 8 quarters up to {trail[-1]}")
                where["fiscal_quarter__in"] = trail
            return where, True, notes

        # A fiscal year as a point-in-time stock means its last snapshot on/before today
        for fy in years:
            q = _last_quarter(today, fy)
            if q:
                quarters.append(q)
        if not quarters and last_label:
            quarters = [last_label]

        resolved_q: list[str] = []
        for q in quarters:
            pq = cal.parse_quarter(q)
            resolved_q.append(cal.label(self._snapshot(pq, last, notes)) if pq else q)
        quarters = list(dict.fromkeys(resolved_q))

        if len(quarters) > 1:
            return {"fiscal_quarter__in": quarters}, True, notes
        if not quarters:
            return {}, False, notes
        pq = cal.parse_quarter(quarters[0])
        if named_month and pq:
            if named_month.month != cal.quarter_end(pq).month:
                notes.append(f"ARR is stored at quarter-end only — {named_month:%b %Y} maps to {cal.arr_month_label(pq)}")
            return {"fiscal_month": cal.arr_month_label(pq)}, False, notes
        return {"fiscal_quarter": quarters[0]}, False, notes

    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        resolved = request.resolved
        intent = resolved.extracted.intent
        where_values: dict[str, Any] = {}

        # 1. Period
        period_where, multi_quarter, notes = self._period_where(resolved.fiscal, intent, request.question)
        where_values.update(period_where)
        for n in notes:
            warn("Period mapping", n)

        # 2. Geo (cfy_geo / cfy_area / cfy_region) — the more specific level wins
        if resolved.geo_detail_filter:
            where_values[resolved.geo_detail_filter.col] = resolved.geo_detail_filter.value
        elif resolved.geo_filter:
            g = resolved.geo_filter
            vals = g.values or [g.value]
            if len(vals) > 1:
                where_values[f"{g.col}__in"] = vals
            else:
                where_values[g.col] = vals[0]

        # 3. Product(s)
        where_values.update(self._product_where(resolved))

        # 4. Company — end user (end_user_id) or, when matched by parent name, the parent (end_user_parent_id)
        af = resolved.account_filter
        where_values.update(self._company_where(af))

        # 5. Segment and order type ("renewing in Q2" / "show renewal quarter" are not a deal-type filter)
        if resolved.segment_filter:
            where_values["market_segment"] = resolved.segment_filter
        order = resolved.order_type_filter
        if order == "Renewal" and _renewal_mode(request.question):
            order = None
        if order:
            where_values["mrr_order_type"] = order

        # 6. Shape — the cut the question asks for ("by product", "by region", "top accounts", "by parent"),
        #    else the total (or the pinned company's total)
        cut = requested_cut(request.question, intent)
        level = resolved.product_level or max([f.deepest_level for f in (resolved.product_filters or [])], default=1) or 1
        group_by: list[str] = []
        select_extra: list[str] = []
        if cut == "product" or (cut == "total" and self._multi_product_group(resolved)):
            group_by = [f"product_l{level}"]
        elif cut in _GEO_COL:
            group_by = [_GEO_COL[cut]]
        elif cut == "segment":
            group_by = ["market_segment"]
        elif cut == "parent":
            group_by, select_extra = ["end_user_parent_id"], ["MAX(end_user_parent_name) AS parent_name"]
        elif cut == "account" or (af and af.multiple):
            group_by, select_extra = ["account_id"], [_NAME_EXPR]
        elif "end_user_id" in where_values or "end_user_id__in" in where_values:
            group_by, select_extra = ["end_user_id"], ["MAX(end_user_name) AS account_name"]
        elif "end_user_parent_id" in where_values or "end_user_parent_id__in" in where_values:
            group_by, select_extra = ["end_user_parent_id"], ["MAX(end_user_parent_name) AS parent_name"]

        if (multi_quarter or intent == Intent.TREND) and "fiscal_quarter" not in group_by:
            group_by = ["fiscal_quarter"] + group_by
        order_by = "total_arr DESC NULLS LAST"
        if "fiscal_quarter" in group_by:
            order_by = "fiscal_quarter ASC" + (", total_arr DESC NULLS LAST" if len(group_by) > 1 else "")

        entity_grouped = bool(select_extra) and cut in ("account", "parent")
        limit_n = resolved.extracted.limit_n or 10
        limit = limit_n if entity_grouped else max(limit_n, 100)
        warn("ARR shape", f"cut={cut}  group_by={group_by or ['(total)']}  limit={limit}")

        return SQLContext(
            normalized_question=request.question,
            intent=intent,
            metric="arr",
            metric_name="ARR",
            metric_variant="snapshot",
            metric_agg=self.metric_def.aggregation,
            primary_table="data_arr",
            join_clause="",
            schema_ddl=self.metric_def.schema_ddl(),
            where_values=where_values,
            group_by=group_by,
            select_extra=select_extra,
            order_by=order_by,
            limit=limit,
        )
