"""Replays real bad extractor outputs through the S1 grounding guard. Run: python3 tests/test_s1_guard.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest import mock  # noqa: E402

import fixtures  # noqa: E402
from core import companies  # noqa: E402
from pipeline.s1_extract import _ground, _infer_intent  # noqa: E402

fixtures.install_hierarchy()
companies.existing = lambda candidates, **kw: set()  # hermetic: no database unless a test patches it

BASE = {"intent": "AGGREGATE", "account_raw": None, "products_raw": [], "geo_raw": [],
        "segment_raw": [], "metric_raw": "ARR", "fiscal_raw": None}


def g(query, **model_out):
    return _ground({**BASE, **model_out}, query)


# fiscal string and hallucinated regions in geo_raw
r = g("Top companies ARR for ZIA for FY 2027 Q1", intent="RANK", products_raw=["ZIA"],
      geo_raw=["EMEA", "APJ", "Americas", "EUC"], segment_raw=["large enterprise"], fiscal_raw="Q1FY27")
assert r["geo_raw"] == [] and r["segment_raw"] == [] and r["products_raw"] == ["ZIA"]
assert r["intent"] == "RANK" and r["operator"] == "top" and r["limit_n"] is None  # no invented limit

r = g("What is the total ARR for ZIA in Q1FY26?", geo_raw=["Q1FY26"], fiscal_raw="Q1FY26", operator="all")
assert r["geo_raw"] == [] and r["operator"] is None and r["limit_n"] is None

# product hallucinated from a segment-only question, and the full product list for 'all products'
r = g("Show me ARR for large enterprise accounts.", products_raw=["ZIA", "ZPA"],
      geo_raw=["large enterprise"], segment_raw=["large enterprise"])
assert r["products_raw"] == [] and r["geo_raw"] == [] and r["segment_raw"] == ["large enterprise"]

r = g("What is total ARR across all products Q1FY26?",
      products_raw=["ZIA", "ZPA", "ZDX", "Platform", "Bundles"], geo_raw=["Q1FY26"], fiscal_raw="Q1FY26")
assert r["products_raw"] == [] and r["geo_raw"] == []

# alias-grounded product, relative fiscal period kept
r = g("What is the ARR for Digital Experience last quarter?", products_raw=["ZDX"],
      geo_raw=["last quarter"], fiscal_raw="last quarter")
assert r["products_raw"] == ["Digital Experience"] and r["geo_raw"] == [] and r["fiscal_raw"] == "last quarter"

# truncated segment restored; country evidences its region; extra regions dropped
r = g("ZPA ARR large enterprise in Germany", products_raw=["ZPA"], segment_raw=["enterprise"], geo_raw=["EMEA", "APJ"])
assert r["segment_raw"] == ["large enterprise"] and r["geo_raw"] == ["EMEA"]

# product/region words are never segments or accounts; 'us' the word is not a region
r = g("Show us ARR for ZIA", account_raw="ZIA", segment_raw=["ZIA"], geo_raw=["AMER"])
assert r["account_raw"] is None and r["segment_raw"] == [] and r["geo_raw"] == []

# named company: kept only if typed; LOOKUP without a company is demoted
r = g("What is ZIA ARR?", intent="LOOKUP", account_raw="Siemens", products_raw=["ZIA"])
assert r["account_raw"] is None and r["intent"] == "AGGREGATE"
assert g("ARR for Accenture Q1FY26", intent="LOOKUP", account_raw="Accenture")["intent"] == "LOOKUP"

# demotion must not block the later rank promotion
assert g("Top companies ARR for ZIA", intent="LOOKUP", account_raw="Top companies")["intent"] == "RANK"

# TREND/COMPARE/RISK need a cue word in the query
assert g("bottom 5 SMB accounts by ARR Q2FY26", intent="TREND")["intent"] == "RANK"
assert g("ZPA ARR trend by quarter", intent="TREND", fiscal_raw="quarter")["intent"] == "TREND"
assert g("ZPA ARR trend by quarter", fiscal_raw="quarter")["fiscal_raw"] is None
assert g("ZIA ARR year to date", fiscal_raw="year to date")["fiscal_raw"] == "year to date"
assert g("ZIA ARR for EMEA", intent="COMPARE")["intent"] == "AGGREGATE"

# a nationality is a region, not an account; a country inside a company name is not evidence of a region
r = g("ZIA ARR for German customers", intent="LOOKUP", account_raw="German", geo_raw=["EMEA"], products_raw=["ZIA"])
assert r["account_raw"] is None and r["geo_raw"] == ["EMEA"] and r["intent"] == "AGGREGATE"
assert g("Indian Oil ARR Q1FY26", intent="LOOKUP", account_raw="Indian Oil", geo_raw=["APJ"])["geo_raw"] == []

# a company filed under segment_raw is moved to account_raw; generic or known-segment words are not
r = g("ZIA and ZPA ARR for Siemens Q1FY26", products_raw=["ZIA", "ZPA"], segment_raw=["Siemens"])
assert r["account_raw"] == "Siemens" and r["segment_raw"] == [] and r["intent"] == "LOOKUP"
r = g("SWG ARR for Indonesian customers FY26", segment_raw=["customers"], products_raw=["SWG"])
assert r["account_raw"] is None and r["segment_raw"] == []
r = g("ZIA ARR for Large Enterprise", segment_raw=["Large Enterprise"])
assert r["account_raw"] is None and r["segment_raw"] == ["Large Enterprise"]
assert g("Major accounts ARR", segment_raw=["Major accounts"])["account_raw"] is None

# explicit metric words override the default metric; DELTA needs a cue
assert g("ZIA downsell EMEA Q1FY26")["metric_raw"] == "CHURN"
assert g("ZIA ACV Q1FY26")["metric_raw"] == "ACV"
assert g("ZIA ARR Q1FY26")["metric_raw"] == "ARR"
assert g("ARR for ZPA in Japan this quarter", intent="DELTA")["intent"] == "AGGREGATE"
assert g("how much did ZDX ARR grow", intent="DELTA")["intent"] == "DELTA"

# a bare number is never a fiscal year ('top 10'), but explicit FY/year forms are
from pipeline.s1_extract import _normalize_fiscal  # noqa: E402
assert _normalize_fiscal("top 10 accounts ZIA") == (None, None)
assert _normalize_fiscal("top 10 accounts ZIA FY26") == ("FY 2026", None)
assert _normalize_fiscal("ZIA ARR Q2FY26") == ("FY 2026", "FY 2026 Q2")
assert _normalize_fiscal("ZIA ARR fiscal year 2027") == ("FY 2027", None)

# products the model missed are recalled from aliases/synonyms; generic words are not
assert g("top 10 accounts by ZPA ARR in EMEA", segment_raw=["ZPA"], geo_raw=["EMEA"])["products_raw"] == ["ZPA"]
assert g("SWG ARR Q1FY26", products_raw=["ZIA"])["products_raw"] == ["SWG"]  # SWG is a level-2 node, not ZIA itself
assert g("ARR by platform strategy")["products_raw"] == []

# limit comes from the text; model-supplied missing_critical never survives
r = g("bottom 5 accounts by ARR", intent="RANK", limit_n=10, missing_critical=["fiscal"])
assert r["operator"] == "bottom" and r["limit_n"] == 5 and r["missing_critical"] == []

# an invalid / missing intent falls back to the cue rules, which must be case-insensitive
assert g("Top companies ARR for ZIA", intent="RANK | LOOKUP | AGGREGATE")["intent"] == "RANK"
assert _infer_intent("who has the highest ARR", None, "top") == "RANK"

# the model found no company: a capitalised phrase that is a real account is recalled from the DB
KNOWN = {"shell", "oracle", "microsoft", "bank of america"}
with mock.patch.object(companies, "existing", side_effect=lambda cands, **kw: {c.lower() for c in cands if c.lower() in KNOWN}):
    assert g("Shell ARR")["account_raw"] == "Shell"
    assert g("ARR for Oracle")["account_raw"] == "Oracle"
    assert g("top products for Microsoft")["account_raw"] == "Microsoft"
    assert g("ARR for Bank of America in Q1FY26")["account_raw"] == "Bank of America"      # longest phrase wins
    assert g("Core SWG ARR trend", products_raw=["Core SWG"])["account_raw"] is None       # product phrases are masked
    assert g("What is the total ARR for ZIA?")["account_raw"] is None                       # query words are not names
    assert g("arr for shell")["account_raw"] == "shell"                                     # lowercase: found at a company slot, confirmed by the account list
    assert g("arr for the quarter")["account_raw"] is None                                  # no account named
    assert g("ARR for Shell", account_raw="Shell")["account_raw"] == "Shell"               # the model's own answer wins
assert g("Shell ARR")["account_raw"] == "Shell"      # a company slot: accepted even if the list does not know it (S2 then says "not found")

# the model files a company under products_raw: it moves to account_raw, real products stay
with mock.patch.object(companies, "existing", side_effect=lambda cands, **kw: {c.lower() for c in cands if c.lower() in KNOWN}):
    r = g("ARR for Oracle", products_raw=["Oracle"])
    assert r["account_raw"] == "Oracle" and r["products_raw"] == []
    r = g("ZIA ARR for Oracle", products_raw=["ZIA", "Oracle"])
    assert r["account_raw"] == "Oracle" and r["products_raw"] == ["ZIA"]

# region words are never companies, even if the account list has names that start with them
with mock.patch.object(companies, "existing", side_effect=lambda cands, **kw: {c.lower() for c in cands}):
    for q in ("ZIA ARR for APJ", "ARR in Japan", "total ARR for German customers", "ZDX vs ZPA ARR for Americas",
              "ZIA ARR for Large Enterprise accounts"):
        assert g(q)["account_raw"] is None, q

# singular 'the top account' means one row; plural and explicit N are unchanged
r = g("Who is the top account by ARR in EMEA in Q1FY26?", intent="RANK", geo_raw=["EMEA"], fiscal_raw="Q1FY26")
assert r["operator"] == "top" and r["limit_n"] == 1
r = g("Top accounts by ARR in EMEA in Q1FY26", intent="RANK", geo_raw=["EMEA"], fiscal_raw="Q1FY26")
assert r["limit_n"] is None
r = g("Top 5 accounts by ARR in EMEA in Q1FY26", intent="RANK", geo_raw=["EMEA"], fiscal_raw="Q1FY26")
assert r["limit_n"] == 5
r = g("Which customer has the biggest ZPA ARR in Q1FY26?", intent="RANK", products_raw=["ZPA"], fiscal_raw="Q1FY26")
assert r["limit_n"] == 1

# an imperative verb that is also an account name ('Take') must not be recalled as the company
from pipeline import s1_extract  # noqa: E402
with mock.patch.object(companies, "existing", lambda cands, **kw: {c.lower() for c in cands if c in ("Take", "Toyota")}):
    r = g("Take the top 20 accounts by ARR in Q1FY26 and compare their Q1FY26 ARR vs Q1FY25 ARR.", intent="COMPARE")
    assert r["account_raw"] is None, r
    r = g("Pull ARR for Toyota in Q1FY26", intent="LOOKUP")                    # a real company is still recalled
    assert r["account_raw"] == "Toyota", r
    r = g("Toyota ARR in Q1FY26", intent="LOOKUP")                              # company as the FIRST word still works
    assert r["account_raw"] == "Toyota", r

print("s1 guard: all checks passed")
