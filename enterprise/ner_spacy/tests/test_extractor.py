"""Deterministic test suite for the no-training extractor.

Run:  python tests/test_extractor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from extractor import Extractor


KNOWN = ["Toyota", "BMW", "Siemens", "Siemens AG", "Microsoft", "HSBC",
         "Shell", "PayPal", "Cisco", "Bank of America", "JPMorgan",
         "Goldman Sachs"]
EX = Extractor(known_companies=KNOWN)


def check(query: str, **want):
    r = EX.extract(query)
    g = r.primary
    actual = {
        "intent": r.intent, "metric": r.metric,
        "operator": r.operator, "limit": r.limit_n,
        "accounts": g.accounts, "products": g.products,
        "geo": g.geo, "segments": g.segments,
        "fiscal": g.fiscal, "n_groups": len(r.groups),
    }
    bad = {k: (actual[k], v) for k, v in want.items() if actual[k] != v}
    assert not bad, f"{query!r}\n   diff: {bad}\n   full: {actual}"


# ── Single-group queries ──────────────────────────────────────────────────────
check("ARR for Toyota in EMEA Q1FY26",
      accounts=["Toyota"], geo=["EMEA"], fiscal="Q1FY26", intent="LOOKUP")

# ── 'X ARR' pattern (position-only, no 'for'/'of' preposition) ──────────────
check("What is HSBC ARR?",   accounts=["HSBC"],   intent="LOOKUP")
check("HSBC ARR Q1FY26",     accounts=["HSBC"],   fiscal="Q1FY26", intent="LOOKUP")
check("Toyota ARR trend",    accounts=["Toyota"], intent="TREND")

# ── 'for X' when metric sits earlier in the sentence, not as X's head ───────
check("What is ARR breakdown by product for HSBC Q1FY26?",
      accounts=["HSBC"], fiscal="Q1FY26", intent="LOOKUP")
check("Show me ARR by region for Siemens FY26",
      accounts=["Siemens"], fiscal="FY26", intent="LOOKUP")

# ── Vendor self-reference ('Zscaler' is never an account) ───────────────────
check("what is the arr for Zscaler",       accounts=[], intent="AGGREGATE")
check("Zscaler ARR Q1FY26",                accounts=[], fiscal="Q1FY26", intent="AGGREGATE")
check("ZS total ARR",                      accounts=[], intent="AGGREGATE")
check("Zscaler's top customer by ARR",     accounts=[], operator="top", intent="RANK")
check("Zscaler ARR for Toyota Q1FY26",     accounts=["Toyota"], intent="LOOKUP")

# ── Order type (data_arr.mrr_order_type: Renewal / Upsell / New) ─────────────
def check_order(query: str, want: list[str], **rest):
    got = EX.extract(query).primary.order_types
    assert got == want, f"{query!r}\n   order_types got {got} expected {want}"
    if rest:
        check(query, **rest)


check_order("What is total ARR for accounts renewing in Q2FY26 across EMEA?", ["Renewal"],
            geo=["EMEA"], fiscal="Q2FY26", accounts=[], intent="AGGREGATE")
check_order("Upsell ARR in APJ FY26", ["Upsell"], geo=["APJ"])
check_order("Show new business ARR for enterprise Q1FY26", ["New"], segments=["Enterprise"])
check_order("Top 10 accounts with upselling in EMEA", ["Upsell"], operator="top", limit=10)
check_order("ARR for Renewal and Upsell orders in APJ Q1FY26", ["Renewal", "Upsell"], n_groups=1)
check_order("What is new ARR for Q1FY26", [], metric="INCR_ARR")        # bare 'new' stays the metric
check_order("ARR for Toyota in EMEA Q1FY26", [])                        # no cue, no order type
check_flat_q = EX.extract("What is total ARR for accounts renewing in Q2FY26 across EMEA?").to_s1_dict()
assert check_flat_q["order_type_raw"] == ["Renewal"], check_flat_q

# ── 'all <dimension>' clears that filter, even next to a narrower value ──────
check("What is Private Access ARR for enterprise and all segments Q1FY26?",
      products=["Private Access"], segments=[], fiscal="Q1FY26", n_groups=1)
check("Give me ARR for EMEA and all geos Q1FY26.", geo=[], fiscal="Q1FY26", n_groups=1)
check("Give me full ARR profile for HSBC in Q1FY26 - all products, total ARR and QoQ change.",
      accounts=["HSBC"], products=[])
check("What is Private Access ARR for enterprise Q1FY26?", segments=["Enterprise"])   # no 'all': filter stays

# ── Relative windows: years, number words, unit typos ───────────────────────
check("ARR trend for Toyota last 3 years", accounts=["Toyota"], fiscal="last 3 years", intent="TREND")
check("ARR for Toyota last three quarters", accounts=["Toyota"], fiscal="last 3 quarters", intent="TREND")
check("ARR for Toyota last 3 quester", fiscal="last 3 quarters", intent="TREND")
check("ARR for Toyota past 2 yaers", fiscal="past 2 years", intent="TREND")
check("ARR for Siemens in the last five fiscal years", accounts=["Siemens"], fiscal="last 5 fiscal years")
check("ARR for the last 5 accounts", fiscal=None)                       # 'accounts' is not a period unit
check("ARR for ZPA last year", fiscal="last year")                       # no count: unchanged

# ── a typed hierarchy node keeps its level; deep and acronym products are found; no silent company drops ──
check("What is Digital Experience ARR?", products=["Digital Experience"])           # not collapsed to the ZDX alias
check("What is JPMorgan Private Access ARR Q1FY26?", accounts=["JPMorgan"], products=["Private Access"])
check("What is Shell total ARR Q1FY26?", accounts=["Shell"])
check("Show me bottom 10 accounts by ARR growth rate in APAC large enterprise Q1FY26.", accounts=[])   # 'rate' is not a company
check("What is EMEA ARR for Q1FY26 and Q2FY26?", fiscal="Q1FY26 and Q2FY26", intent="COMPARE")

check("Give me Internet Access ARR for Siemens in EMEA but their global number as well Q1FY26.",
      segments=[], accounts=["Siemens"])                                   # 'global' is a word here, not a segment
check("Compare total platform ARR for enterprise in EMEA Q1FY26", products=[])   # 'platform' alone is not a product

# ── typo'd query-grammar words don't glue into company chunks ────────────────
# ('totl' / 'accoutns' / 'revenu' / 'waht'); the fixture account list stands in for the real dim_account.
check("Shell totl ARR", accounts=["Shell"])

# ── Fiscal range ('from A to B', 'A through B') ─────────────────────────────
check("Which top 10 EMEA enterprise accounts had the highest ARR growth from Q4FY25 to Q1FY26?",
      geo=["EMEA"], segments=["Enterprise"], operator="top", limit=10,
      metric="ARR", intent="DELTA", fiscal="Q4FY25 to Q1FY26", n_groups=1)
check("ARR for Toyota from FY25 to FY26",
      accounts=["Toyota"], fiscal="FY25 to FY26", n_groups=1)
check("Siemens ARR Q4FY25 through Q1FY27",
      accounts=["Siemens"], fiscal="Q4FY25 to Q1FY27", n_groups=1)

# ── Trailing context ('for APAC Q1FY26') is shared by every side ────────────
def check_flat(query: str, **want):
    d = EX.extract(query).to_s1_dict()
    bad = {k: (d[k], v) for k, v in want.items() if d[k] != v}
    assert not bad, f"{query!r}\n   flat diff: {bad}\n   full: {d}"


Q_SPLIT = "What is the ARR split between Private Access and Internet Access for APAC Q1FY26?"
check(Q_SPLIT, products=["Private Access"], geo=["APJ"], fiscal="Q1FY26", n_groups=2)
check_flat(Q_SPLIT, products_raw=["Private Access", "ZIA"], geo_raw=["APJ"], fiscal_raw="Q1FY26")
check_flat("Compare ARR for companies in EMEA in 2026 vs companies in AMER in 2027",
           geo_raw=["EMEA", "Americas"], fiscal_raw="2026 vs 2027")
check_flat("Toyota ARR Q1FY26 vs Q1FY25", fiscal_raw="Q1FY26 vs Q1FY25")

# ── Chained accounts: 'A and B', 'A, B and C', 'A or B' ─────────────────────
check("Give me ARR for Siemens and Toyota Q1FY26",
      accounts=["Siemens", "Toyota"], fiscal="Q1FY26", n_groups=1)
check("ARR for Siemens, Toyota and BMW FY26",
      accounts=["Siemens", "Toyota", "BMW"], n_groups=1)
check("Toyota or BMW ARR", accounts=["Toyota", "BMW"], n_groups=1)

# ── Query-grammar words are never accounts ('accounts', 'geos', 'regions') ──
check("What is AI Security ARR for enterprise accounts across all geos Q1FY27?",
      accounts=[], products=["AI Security"], segments=["Enterprise"], geo=[],
      fiscal="Q1FY27", intent="AGGREGATE")
check("ARR across all regions FY26",       accounts=[], geo=[], fiscal="FY26")
check("all customers by product Q1FY26",   accounts=[], fiscal="Q1FY26")
check("ARR for Toyota across all geos",    accounts=["Toyota"], geo=[])

check("Top 10 accounts by ZPA ARR in APJ enterprise last 4 quarters",
      products=["ZPA"], geo=["APJ"], segments=["Enterprise"],
      operator="top", limit=10, intent="TREND")

check("What is the ARR for ZTNA in Americas FY 2026?",
      products=["ZPA"], geo=["Americas"], fiscal="FY 2026", intent="AGGREGATE")

check("Bottom 5 accounts by churn in EMEA Q1FY26",
      geo=["EMEA"], operator="bottom", limit=5, metric="CHURN", intent="RISK")

# ── Fuzzy typo: company ──────────────────────────────────────────────────────
check("Siemnes ARR Q1FY26", accounts=["Siemens"], fiscal="Q1FY26", intent="LOOKUP")
check("Toytoa ARR in EMEA Q1FY26", accounts=["Toyota"], geo=["EMEA"])

# ── Fuzzy typo: geo (short 4-char and long) ─────────────────────────────────
check("ARR in EMAE Q1FY26",       geo=["EMEA"],     fiscal="Q1FY26")
check("ARR in Americsa FY2026",   geo=["Americas"], fiscal="FY2026")
check("ARR for Shell in Europe",  accounts=["Shell"], geo=["EMEA"])

# ── Fuzzy typo: product + segment ───────────────────────────────────────────
check("ZPAN ARR Q1FY26 for enterprize",
      products=["ZPA"], segments=["Enterprise"], fiscal="Q1FY26")

# ── Fuzzy typo: multi-word product (bigram pass) ─────────────────────────────
check("Give me Digital Experince ARR for APJ Q1FY26",
      products=["Digital Experience"], geo=["APJ"], fiscal="Q1FY26", accounts=[])
check("Private Acces ARR for EMEA Q1FY26",
      products=["Private Access"], geo=["EMEA"], fiscal="Q1FY26")

# ── Live product catalog (L1-L3 from data_arr seed) ─────────────────────────
check("Firewall ARR Q1FY26",   products=["Firewall"],   fiscal="Q1FY26")
check("DSPM ARR for enterprise APJ FY26",
      products=["DSPM"], segments=["Enterprise"], geo=["APJ"], fiscal="FY26")
check("ZT Browser growth EMEA", products=["ZT Browser"], geo=["EMEA"])
check("Core SWG downsell last 4 quarters",
      products=["Core SWG"], fiscal="last 4 quarters", metric="CHURN", intent="RISK")

# ── Normalisation ────────────────────────────────────────────────────────────
check("Give me ARR for Toyota in EMEA for last 4 Quaters",
      accounts=["Toyota"], geo=["EMEA"], fiscal="last 4 quarters", intent="TREND")

# ── Fiscal: year-first and 'quarter N' forms ────────────────────────────────
check("ARR for Toyota 2027 Q1",         accounts=["Toyota"], fiscal="2027 Q1")
check("HSBC ARR 2026 Q3",               accounts=["HSBC"],   fiscal="2026 Q3")
check("ARR for Siemens quarter 2 FY27", accounts=["Siemens"], fiscal="quarter 2 FY27")
check("Toyota 2026 quarter 1 ARR",      accounts=["Toyota"], fiscal="2026 quarter 1")

# ── 'A and B' is a LIST, not a comparison, without a cue word ───────────────
check("What is Private Access and Digital Experience ARR for EMEA Q1FY26?",
      products=["Private Access", "Digital Experience"], geo=["EMEA"], fiscal="Q1FY26",
      n_groups=1, intent="AGGREGATE")
check("Toyota and BMW ARR Q1FY26",
      accounts=["Toyota", "BMW"], fiscal="Q1FY26", n_groups=1)

# ── Comparison: full form ────────────────────────────────────────────────────
check("Compare ARR for companies in EMEA in 2026 vs companies in AMER in 2027",
      intent="COMPARE", n_groups=2)

check("Compare Siemens and Toyota ARR for FY26",
      n_groups=2, intent="COMPARE")

check("Toyota ARR Q1FY26 vs Q1FY25",
      accounts=["Toyota"], n_groups=2, intent="COMPARE")

# ── Lead-verb must NOT be treated as a company ───────────────────────────────
check("Show me ARR for Toyota in Q1FY26",
      accounts=["Toyota"], intent="LOOKUP")

check("Take the top 20 accounts by ARR in Q1FY26 and compare their ARR to Q1FY25",
      operator="top", limit=20, intent="COMPARE")

# ── Short acronym case sensitivity: 'us' should not be a region ──────────────
check("tell us what the ARR is for Shell", accounts=["Shell"], geo=[])

print("all extractor tests passed")
