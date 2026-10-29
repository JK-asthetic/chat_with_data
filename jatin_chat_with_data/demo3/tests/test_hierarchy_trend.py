"""Hierarchy resolution, TREND default window, S3 card, S4 WHERE/GROUP BY and S5 rendering.

No LLM and no database. Run: python3 tests/test_hierarchy_trend.py
"""
import builtins
import contextlib
import io
from datetime import date
from unittest import mock

import psycopg2

import fixtures  # noqa: E402  (also puts the project root on sys.path)
from core import hierarchy
from core.fiscal import quarter_of, trailing_quarters
from pipeline import s2_resolve, s3_clarify, s4_context, s5_generate
from pipeline.models import ExtractedQuery, Fiscal, Intent, ProductFilter, ResolvedEntities, SQLContext
from pipeline.s1_extract import _ground, _normalize_fiscal

fixtures.install_hierarchy()

# ── hierarchy index ──────────────────────────────────────────────────────────
assert hierarchy.find("Core SWG") == (("ZIA", "SWG", "Core SWG"),)
assert hierarchy.find(" swg ") == (("ZIA", "SWG"),)
assert hierarchy.find("ZIA") == (("ZIA",),)
assert hierarchy.find("Sandbox") == (("ZIA", "Sandbox"),)          # repeated leaf levels are not extra nodes
assert len(hierarchy.find("China Premium")) == 2                    # genuinely under two parents
assert len(hierarchy.find("Firewall")) == 2
assert hierarchy.find("nonexistent") == ()
assert "Core SWG" in hierarchy.names(3) and "Proxy Port" not in hierarchy.names(3)

# a failed load is not cached and degrades to "no hierarchy"
hierarchy._INDEX = None
with mock.patch("core.hierarchy.query_all", side_effect=psycopg2.OperationalError("down")), \
        contextlib.redirect_stdout(io.StringIO()):
    assert hierarchy.find("Core SWG") == () and hierarchy._INDEX is None
fixtures.install_hierarchy()

# ── S2 product resolution ────────────────────────────────────────────────────
def resolve(*raw):
    return s2_resolve._validate_products(list(raw))

f, amb, cand, hier = resolve("Core SWG")
assert [p.path for p in f] == [("ZIA", "SWG", "Core SWG")] and f[0].deepest_level == 3 and f[0].l3 == "Core SWG"
assert resolve("SWG")[0][0].path == ("ZIA", "SWG")
assert resolve("Secure Web Gateway")[0][0].path == ("ZIA", "SWG")          # alias pointing at a hierarchy name
assert resolve("Digital Experience")[0][0].path == ("Digital Experience",)
assert resolve("DEM")[0][0].path == ("Digital Experience", "ZDX")
assert resolve("ZCP")[0][0].path == ("ZCP",)                                # stale alias still works as l1
f, amb, cand, hier = resolve("China Premium")
assert f == [] and sorted(hier["China Premium"]) == [["ZIA", "SWG", "China Premium"], ["ZPA", "Private Access", "China Premium"]]
assert [p.path for p in resolve("ZIA", "SWG")[0]] == [("ZIA", "SWG")]       # sub-product beats its own ancestor

# ── S1 keeps the full hierarchy name ─────────────────────────────────────────
with contextlib.redirect_stdout(io.StringIO()):
    q = "Core SWG ARR trend for 2027 Q1"
    assert _ground({"intent": "TREND", "products_raw": ["SWG"], "fiscal_raw": "2027 Q1"}, q)["products_raw"] == ["Core SWG"]
    assert _ground({"intent": "AGGREGATE", "products_raw": ["ZIA"]}, "SWG ARR Q1FY26")["products_raw"] == ["SWG"]
    assert _ground({"intent": "AGGREGATE"}, "Sandbox vs Core SWG ARR")["products_raw"] == ["Core SWG", "Sandbox"]
assert _normalize_fiscal(q) == ("FY 2027", "FY 2027 Q1")

# ── fiscal calendar and TREND window ─────────────────────────────────────────
assert quarter_of(date(2026, 10, 26)) == ("FY 2027", "FY 2027 Q1")
assert trailing_quarters("FY 2027 Q1", 6) == [
    "FY 2025 Q4", "FY 2026 Q1", "FY 2026 Q2", "FY 2026 Q3", "FY 2026 Q4", "FY 2027 Q1"]

def window(intent, fiscal=None, raw="", fiscal_raw=None):
    ext = ExtractedQuery(raw_query=raw, intent=intent, fiscal_raw=fiscal_raw)
    w = s2_resolve._trend_window(ext, fiscal or Fiscal(), today=date(2026, 10, 26))
    return w and w.quarter_labels

SIX = trailing_quarters("FY 2027 Q1", 6)
assert window(Intent.TREND) == SIX                                                         # no period → ends now
assert window(Intent.TREND, Fiscal(fiscal_quarter_label="FY 2027 Q1")) == SIX             # one quarter → ends there
assert window(Intent.TREND, Fiscal(fiscal_quarter_label="FY 2026 Q2"))[-1] == "FY 2026 Q2"
assert window(Intent.TREND, Fiscal(fiscal_year_label="FY 2026")) is None                  # a year is already a range
assert window(Intent.TREND, Fiscal(quarter_labels=["FY 2026 Q1", "FY 2026 Q2"], is_range=True)) is None
assert window(Intent.AGGREGATE) is None
assert len(window(Intent.TREND, raw="ZIA ARR over the last 4 quarters")) == 4

# ── relative periods resolve against today's fiscal quarter (2026-10-26 = FY 2027 Q1) ──
NOW = date(2026, 10, 26)
rel = lambda text, today=NOW: s2_resolve._parse_relative(text, today)
assert rel("last quarter").fiscal_quarter_label == "FY 2026 Q4" and rel("last quarter").fiscal_year_label == "FY 2026"
assert rel("previous quarter").fiscal_quarter_label == "FY 2026 Q4"
assert rel("this quarter").fiscal_quarter_label == "FY 2027 Q1" and rel("current quarter").quarter == 1
assert rel("last 6 quarters").quarter_labels == SIX and rel("last 6 quarters").is_range
assert rel("past 2 quarters").quarter_labels == ["FY 2026 Q4", "FY 2027 Q1"]
assert rel("last 3 years").quarter_labels == s2_resolve.trailing_quarters("FY 2027 Q1", 12)   # a year is 4 quarters
assert len(rel("last 3 years").quarter_labels) == 12 and rel("last 3 years").is_range
assert len(rel("past 2 fiscal years").quarter_labels) == 8
assert len(rel("last 10 years").quarter_labels) == 20                                            # capped like quarters
assert rel("last year").fiscal_year_label == "FY 2026"                                          # no count: previous fiscal year
assert rel("last year").fiscal_year_label == "FY 2026" and rel("this year").fiscal_year_label == "FY 2027"
assert rel("ytd").quarter_labels == ["FY 2027 Q1"]
assert rel("year to date", date(2027, 3, 1)).quarter_labels == ["FY 2027 Q1", "FY 2027 Q2", "FY 2027 Q3"]
assert rel("ZIA ARR by region") is None and rel("") is None
assert rel("last quarter", date(2026, 3, 1)).fiscal_quarter_label == "FY 2026 Q2"   # crosses the fiscal year boundary

# an explicit period beats a relative one, and ranges skip DB validation
import asyncio
res, ok, _ = asyncio.run(s2_resolve._tool_fiscal("last 6 quarters", None, None, "ZIA ARR for the last 6 quarters"))
assert ok and len(res.quarter_labels) == 6 and res.quarter_labels[-1].startswith("FY ")

# S1: a multi-quarter window is a TREND, never a summed snapshot
with contextlib.redirect_stdout(io.StringIO()):
    r = _ground({"intent": "AGGREGATE", "products_raw": ["ZIA"], "fiscal_raw": "last 6 quarters"}, "ZIA ARR for the last 6 quarters")
assert r["intent"] == "TREND" and r["fiscal_raw"] == "last 6 quarters"

# ── S3 hierarchy card ────────────────────────────────────────────────────────
PATHS = [["ZIA", "SWG", "China Premium"], ["ZPA", "Private Access", "China Premium"]]
def ask(answer):
    with mock.patch.object(builtins, "input", return_value=answer), contextlib.redirect_stdout(io.StringIO()):
        return s3_clarify._ask_product_hierarchy("China Premium", PATHS)
assert ask("").path == ("ZIA", "SWG", "China Premium")
assert ask("2").path == ("ZPA", "Private Access", "China Premium") and ask("2").deepest_level == 3
assert ask("3") is None

# ── S4 WHERE / GROUP BY / context ────────────────────────────────────────────
P = ProductFilter.from_path
assert s4_context._product_where([P(("ZIA", "SWG", "Core SWG"))]) == {
    "product_l1": "ZIA", "product_l2": "SWG", "product_l3": "Core SWG"}
assert s4_context._product_where([P(("ZIA",)), P(("ZPA",))]) == {"product_l1__in": ["ZIA", "ZPA"]}
assert s4_context._product_where([P(("ZIA", "SWG", "Core SWG")), P(("ZPA", "Private Access", "Core ZPA"))]) == {
    "product_l3__in": ["Core SWG", "Core ZPA"], "product_l1__in": ["ZIA", "ZPA"]}
assert s4_context._product_where([P(("ZIA", "SWG")), P(("ZPA",))]) == {
    "__or__": [{"product_l1": "ZIA", "product_l2": "SWG"}, {"product_l1": "ZPA"}]}

resolved = ResolvedEntities(
    extracted=ExtractedQuery(raw_query="Core SWG ARR trend", intent=Intent.TREND),
    product_filter=[P(("ZIA", "SWG", "Core SWG"))], fiscal=Fiscal(quarter_labels=SIX, is_range=True))
agg = s4_context._compute_aggregation(resolved)
assert s4_context._build_group_by(resolved, agg) == [
    "product_l1", "product_l2", "product_l3", "fiscal_year", "fiscal_quarter"]
_, ctx = s4_context.build_context(resolved)
assert ctx.where_values["fiscal_quarter__in"] == SIX and ctx.where_values["product_l3"] == "Core SWG"
assert ctx.limit == 1000 and "FY 2025 Q4 to FY 2027 Q1" in ctx.normalized_question

# ── S4 row limit: explicit N wins, ranked lists default to 10, everything else gets only the safety cap ──
def limit_for(intent, n=None):
    return s4_context._row_limit(ExtractedQuery(raw_query="q", intent=intent, limit_n=n))
assert limit_for(Intent.RANK, 5) == 5 and limit_for(Intent.RANK) == 10 and limit_for(Intent.RISK) == 10
assert limit_for(Intent.AGGREGATE) == 1000 and limit_for(Intent.COMPARE) == 1000 and limit_for(Intent.TREND) == 1000

# ── S5 rendering and validator ───────────────────────────────────────────────
where = {"__or__": [{"product_l1": "ZPA"}, {"product_l1": "ZIA", "product_l2": "SWG"}],
         "fiscal_quarter__in": ["FY 2027 Q1"], "end_user_name": "O'Brien"}
assert s5_generate._where_parts(where) == [
    "((product_l1 = 'ZPA') OR (product_l1 = 'ZIA' AND product_l2 = 'SWG'))",
    "fiscal_quarter IN ('FY 2027 Q1')",
    "end_user_name = 'O''Brien'"]
sql = ("SELECT product_l1, SUM(arr) AS total_arr FROM data_arr "
       "WHERE ((product_l1 = 'ZPA') OR (product_l1 = 'ZIA' AND product_l2 = 'SWG')) "
       "AND fiscal_quarter IN ('FY 2027 Q1') GROUP BY product_l1 LIMIT 10;")
ctx5 = SQLContext(normalized_question="q", intent=Intent.AGGREGATE, schema_ddl="",
                  where_values={k: where[k] for k in ("__or__", "fiscal_quarter__in")})
assert s5_generate.validate(sql, ctx5) == []

print("hierarchy / trend / S3-S5 checks: all passed")
