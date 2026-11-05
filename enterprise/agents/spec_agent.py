"""Spec Agent — one generic agent for every metric defined by a `spec` in metrics.yaml.

It turns the resolved entities into, per source table:
  * the period (each metric family has its own semantics — flow quarter, pipeline close quarter,
    renewal window, snapshot quarter, quantity month),
  * the filters (via core.table_profiles — the column differs per table),
  * the cut (total | product | account | parent) with the cuts the metric really supports,
and renders the standard query for it (sql.standard) as the reference / fallback for the SQL generator.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from agents.base_agent import MetricAgent
from core import fiscal_calendar as cal
from core.log import warn
from core.table_profiles import PROFILES, table_filters
from pipeline.models import Fiscal, Intent, MetricAgentRequest, SQLContext
from sql import standard

_WANTS_PARENT = re.compile(r"\bparent|\bgroup compan|\bat the parent\b", re.I)
_WANTS_ACCOUNT = re.compile(r"\b(?:accounts?|customers?|logos?|companies)\b", re.I)
_WANTS_LIST = re.compile(r"\b(?:top|bottom|which|list|rank\w*|biggest|largest|highest|lowest|each|per|by)\b", re.I)
_WANTS_PRODUCT = re.compile(r"\b(?:by|per|each|every|across|all)\s+(?:the\s+)?(?:product|products|l[1-5])\b|\bproduct[- ]wise\b|\bbreakdown\b|\bsplit\b", re.I)
_LOST = re.compile(r"\blost\b|closed[- ]lost", re.I)
_STAGE = re.compile(r"\bstages?\b|stage[- ]wise", re.I)
_OPEN_DEALS = re.compile(r"\bopen deals?\b|\bslipp\w+|\bpast[- ]due\b|\boverdue\b", re.I)


def _label(q: cal.Quarter) -> str:
    return cal.label(q)


def _period_dict(col: str, quarters: list[str], op: str = "") -> dict[str, Any]:
    if op:
        return {f"{col}__{op}": quarters[0]}
    return {f"{col}__in": quarters} if len(quarters) > 1 else {col: quarters[0]}


class SpecAgent(MetricAgent):
    def __init__(self, metric_name: str):
        super().__init__(metric_name)
        self.spec = self.metric_def.spec
        self.kind = self.spec.get("kind", "flow")
        self.tables: list[str] = self.spec.get("tables", [self.metric_def.table])

    # ------------------------------------------------------------------ periods
    def _named_quarters(self, fiscal: Optional[Fiscal], last: cal.Quarter) -> tuple[list[cal.Quarter], bool, bool]:
        """(quarters named in the question, came_from_a_year, is_relative_range)."""
        if not fiscal:
            return [], False, False
        periods = [p for p in (fiscal, fiscal.compare_to) if p]
        out: list[cal.Quarter] = []
        from_year = False
        ranged = False
        for p in periods:
            if p.month_start:
                out.append(cal.quarter_of(date.fromisoformat(p.month_start)))
            elif p.fiscal_quarter_label and cal.parse_quarter(p.fiscal_quarter_label):
                out.append(cal.parse_quarter(p.fiscal_quarter_label))
            elif p.quarter_labels:
                ranged = True
                out.extend(cal.parse_quarter(x) for x in cal.clamp_range(p.quarter_labels, last) if cal.parse_quarter(x))
            elif p.fiscal_year_label:
                from_year = True
                fy = int(p.fiscal_year_label.split()[1])
                qs = cal.quarters_of_year(fy)
                out.extend([x for x in qs if x <= last] or qs)
        return list(dict.fromkeys(out)), from_year, ranged

    def _period(self, resolved, question: str, last: cal.Quarter, notes: list[str]) -> dict[str, Any]:
        """Returns {quarters, by_quarter, variant, op} for the metric's period semantics."""
        intent = resolved.extracted.intent
        named, from_year, ranged = self._named_quarters(resolved.fiscal, last)
        variant = ""

        if self.kind == "pipeline":
            variant = ("lost" if _LOST.search(question) else "stage" if _STAGE.search(question)
                       else "open_deals" if _OPEN_DEALS.search(question) else "open")
            op = ""
            if not named:
                if variant == "lost":
                    named = [last]
                elif variant == "open_deals":
                    named, op = [last], "lte"
                else:
                    named = [cal.next_quarter(last)]
                    notes.append(f"no period named — open pipeline closing in the next quarter {_label(named[0])}")
            elif variant == "open_deals":
                op = "lte"
            return {"quarters": [_label(q) for q in named], "by_quarter": len(named) > 1, "variant": variant, "op": op}

        if self.kind == "risk":
            if not named:
                named = [cal.next_quarter(cal.next_quarter(last))]
                notes.append(f"no period named — renewals due two quarters after the latest complete quarter: {_label(named[0])}")
            return {"quarters": [_label(q) for q in named], "by_quarter": len(named) > 1, "variant": "", "op": ""}

        trend = intent == Intent.TREND
        if not named:
            named = cal.trailing(last, 8) if trend else [last]
            if trend:
                notes.append(f"no period named — trailing 8 quarters up to {_label(last)}")
        elif self.kind == "snapshot_quarter" and from_year:
            named = [named[-1]]                                   # a stock at year end = its last quarter
        for q in named:
            if q > last and self.kind != "pipeline":
                notes.append(f"{_label(q)} is still in progress or in the future — figures may be partial or missing")
        by_q = trend or intent == Intent.COMPARE or (len(named) > 1 and not from_year)
        return {"quarters": [_label(q) for q in named], "by_quarter": by_q, "variant": variant, "op": ""}

    # ------------------------------------------------------------------ cut
    def _cut(self, resolved, question: str, notes: list[str]) -> tuple[str, int]:
        cuts = self.metric_def.cuts or ["product"]
        intent = resolved.extracted.intent
        af = resolved.account_filter
        wants_parent = bool(_WANTS_PARENT.search(question))
        wants_listing = bool(_WANTS_LIST.search(question)) and bool(_WANTS_ACCOUNT.search(question)) or intent == Intent.RANK
        filters = resolved.product_filters or ([resolved.product_filter] if resolved.product_filter else [])
        level = resolved.product_level or max([f.deepest_level for f in filters], default=1) or 1

        if cuts == ["product"]:
            return "product", level
        if self.kind == "pipeline" and (_LOST.search(question) or _OPEN_DEALS.search(question)) \
                and _WANTS_LIST.search(question) and not _WANTS_PRODUCT.search(question) and not (af and af.account_id):
            return ("account" if re.search(r"\baccounts?\b", question, re.I) else "parent"), level   # top lists merge per parent
        if resolved.product_level or len(filters) > 1 or _WANTS_PRODUCT.search(question):
            return "product", level
        if af and af.account_id:
            return "total", level
        if wants_parent and "parent" in cuts:
            return "parent", level
        if wants_listing:
            if "account" in cuts:
                return "account", level
            if "parent" in cuts:
                notes.append(f"{self.metric_def.display_name} is not available per account — showing it per parent company")
                return "parent", level
            return "product", level
        if wants_parent and "parent" not in cuts:
            notes.append(f"{self.metric_def.display_name} has no parent-company cut")
        return "total", level

    # ------------------------------------------------------------------ context
    def build_context(self, request: MetricAgentRequest) -> SQLContext:
        resolved = request.resolved
        question = request.question
        notes: list[str] = []
        today = date.today()
        last = cal.last_complete_quarter(today)

        if self.kind == "composite_arpu":
            return self._arpu_context(request, last)

        period = self._period(resolved, question, last, notes)
        quarters: list[str] = period["quarters"]
        closed = [q for q in quarters if (cal.parse_quarter(q) or last) <= last] or [_label(last)]
        cut, level = self._cut(resolved, question, notes)

        where: dict[str, dict[str, Any]] = {}
        for table in self.tables:
            profile = PROFILES[table]
            w, tnotes, blocked = table_filters(profile, resolved, closed)
            if blocked:
                return self._blocked(request, f"{self.metric_def.display_name}: {blocked}.", notes + tnotes)
            notes += [n for n in tnotes if n not in notes]
            if table == "data_quantity":                          # quantity-month period (attach rate)
                w.update(self._quantity_period(resolved))
            else:
                w.update(_period_dict(profile.period_col, quarters, period["op"]))
            where[table] = w

        if self.kind == "quantity_month":                          # attach-rate denominator: every customer, any product
            bare = resolved.model_copy(update={"product_filter": None, "product_filters": [], "product_level": None})
            wall, _, _ = table_filters(PROFILES["data_quantity"], bare, closed)
            wall.update(self._quantity_period(resolved))
            where["data_quantity_all"] = wall

        for n in notes:
            warn("Period / cut", n)

        limit = resolved.extracted.limit_n or 10
        if cut in ("product", "total") and not re.search(r"\b(?:top|bottom|first|largest|biggest)\s+\d+", question, re.I):
            limit = max(limit, 100)
        plan = standard.Plan(
            metric=self.metric_name, where=where, cut=cut, by_quarter=period["by_quarter"], limit=limit,
            level=level, extra={"explicit_level": bool(resolved.product_level)}, variant=period["variant"] or ("new_logos" if self._new_logo_question(question) else
                                                       "top" if self.metric_name == "CHURN" and cut == "parent" and _WANTS_LIST.search(question) else ""),
        )
        return self._context(request, plan, where, notes)

    @staticmethod
    def _new_logo_question(question: str) -> bool:
        return bool(re.search(r"\bnew[- ]logos?\b", question, re.I)) and not re.search(r"\bn/?u\b|\bupsell\b|\bnew[- ]to[- ]product\b", question, re.I)

    @staticmethod
    def _quantity_period(resolved) -> dict[str, Any]:
        from agents.quantity_agent import QuantityAgent
        w, _, _ = QuantityAgent("QTY")._period_where(resolved.fiscal, resolved.extracted.intent)
        return w

    def _context(self, request: MetricAgentRequest, plan: standard.Plan, where: dict[str, dict[str, Any]], notes: list[str]) -> SQLContext:
        cuts = self.metric_def.cuts or ["product"]
        primary = self.tables[0]
        product_col = {"data_renewal_risk": "product_rl1", "t3_arr_detail": "product",
                       "data_nacv_target": f"fy27_product_l{min(plan.level, 3)}"}.get(primary, f"product_l{plan.level}")
        group_by = {"product": [product_col], "account": ["account_id"], "parent": ["end_user_parent_id"], "total": []}[plan.cut]
        if plan.by_quarter:
            group_by = ["fiscal_quarter"] + group_by
        return SQLContext(
            normalized_question=request.question,
            intent=request.resolved.extracted.intent,
            metric=self.metric_def.value_column,
            metric_name=self.metric_name,
            metric_variant=self.metric_def.variant,
            metric_agg=self.metric_def.aggregation,
            primary_table=primary,
            schema_ddl="\n\n".join(self._ddl(t) for t in self.tables),
            where_values=where[primary],
            extra_where={t: where[t] for t in self.tables[1:] if t in where},
            group_by=group_by,
            order_by="",
            limit=plan.limit,
            reference_sql=standard.reference(plan, cuts),
            fallback_sql=standard.build(plan) or "",
            notes=notes,
        )

    def _ddl(self, table: str) -> str:
        from core.mdl import CATALOG
        return CATALOG[table].ddl((1, 2)) if table in CATALOG else f"-- {table}"

    def _blocked(self, request: MetricAgentRequest, reason: str, notes: list[str]) -> SQLContext:
        return SQLContext(
            normalized_question=request.question, intent=request.resolved.extracted.intent,
            metric=self.metric_def.value_column, metric_name=self.metric_name, primary_table=self.tables[0],
            blocked_reason=reason, notes=notes,
        )

    def _arpu_context(self, request: MetricAgentRequest, last: cal.Quarter) -> SQLContext:
        from agents.arr_agent import ARRAgent
        from agents.quantity_agent import QuantityAgent
        arr = ARRAgent("ARR").build_context(request)
        qty = QuantityAgent("QTY").build_context(request)
        notes = list(dict.fromkeys(arr.notes + qty.notes))
        resolved = request.resolved
        cut, level = self._cut(resolved, request.question, notes)
        if cut == "parent":
            notes.append("parent ARPU is not provided — showing it in total")
            cut = "total"
        where = {"data_arr": arr.where_values, "data_quantity": qty.where_values}
        plan = standard.Plan(metric="ARPU", where=where, cut=cut, limit=resolved.extracted.limit_n or 10, level=1)
        ctx = self._context(request, plan, where, notes)
        return ctx.model_copy(update={"primary_table": "data_arr", "where_values": arr.where_values,
                                      "extra_where": {"data_quantity": qty.where_values},
                                      "schema_ddl": self._ddl("data_arr") + "\n\n" + self._ddl("data_quantity")})
