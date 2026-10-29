"""S1 rule-based extractor: query -> intent / account / products / geo / segment / metric / period.
Hermetic (fixture hierarchy + a fake account list). Includes every query that failed earlier in the project.
Run: python3 tests/test_s1_rules.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fixtures  # noqa: E402
from core import companies, hierarchy  # noqa: E402
from pipeline import s1_extract  # noqa: E402

fixtures.install_hierarchy()
hierarchy._INDEX = hierarchy.build_index(fixtures.ROWS + [dict(zip(
    ("product_l1", "product_l2", "product_l3", "product_l4", "product_l5"), (n, n, n, n, n)))
    for n in ("Data Security", "Agentic SecOps", "ZT Branch")]
    + [dict(product_l1="ZIA", product_l2="Sandbox", product_l3="Sandbox", product_l4="Sandbox",
            product_l5="Advanced Sandbox")])
KNOWN = {"toyota", "bmw", "siemens", "siemens ag", "microsoft", "google", "bank of america", "take", "shell"}
companies.existing = lambda cands, exact=False: {c.lower() for c in cands if c.lower() in KNOWN}


def ex(q):
    e = s1_extract.extract(q)
    return {"intent": e.intent.value, "account": e.account_raw, "products": e.products_raw, "geo": e.geo_raw,
            "segment": e.segment_raw, "metric": e.metric_raw, "fiscal": e.fiscal_raw, "op": e.operator, "limit": e.limit_n}


def check(q, **want):
    got = ex(q)
    bad = {k: (got[k], v) for k, v in want.items() if got[k] != v}
    assert not bad, f"{q!r}\n   got/expected: {bad}\n   full: {got}"


# ── the queries that went wrong earlier ──────────────────────────────────────
check("Which EMEA large enterprise accounts had Data Security downsell greater than 500K Q1FY26?",
      intent="RISK", account=None, products=["Data Security"], geo=["EMEA"], segment=["large enterprise"],
      metric="CHURN", fiscal="Q1FY26")
check("Give me ARR trend for Private Access, enterprise account IN EMEA for last 4 Quaters",
      intent="TREND", account=None, products=["Private Access"], geo=["EMEA"], segment=["enterprise"],
      fiscal="last 4 quarters")                                   # 'enterprise' is a segment, never a product; typo fixed
check("Take the top 20 accounts by ARR in Q1FY26 and compare their Q1FY26 ARR vs Q1FY25 ARR.",
      intent="COMPARE", account=None, op="top", limit=20, fiscal="Q1FY26 vs Q1FY25")      # 'Take' is a verb, not a company
check("Give me accounts with consecutive ARR decline across last 3 quarters on Internet Access in EMEA enterprise "
      "— ranked by total ARR lost.", intent="RISK", products=["Internet Access"], geo=["EMEA"],
      segment=["enterprise"], fiscal="last 3 quarters")
check("Who is the top account by ARR in EMEA in Q1FY26?", intent="RANK", op="top", limit=1, geo=["EMEA"])
check("Which has higher ARR — Siemens or Toyota in q1 2027", account="Siemens", fiscal="q1 2027")
check("Show me ARR for Toyota and BMW Q1FY26.", account="Toyota", fiscal="Q1FY26")

# ── a deeper product name beats the shorter one inside it ('Advanced Sandbox' is level 5, 'Sandbox' level 2) ──
check("Which company has invested in Advanced Sandbox?", products=["Advanced Sandbox"])
check("Which company has invested in Sandbox?", products=["Sandbox"])
check("ARR for Sandbox and Advanced Sandbox Q1FY26", products=["Advanced Sandbox", "Sandbox"], fiscal="Q1FY26")
check("Show ARR for Proxy Port", products=["Proxy Port"])           # a multi-word level-5 name is matched
check("Show ARR for ZIA with logging", products=["ZIA"])            # one-word deep names are not read as products

# ── intent ───────────────────────────────────────────────────────────────────
for q, intent in [
    ("What is the total ARR for ZPA in EMEA in Q1FY26?", "AGGREGATE"),
    ("Top 5 accounts by ARR in EMEA in Q1FY26", "RANK"),
    ("Bottom 10 accounts by ZPA ARR", "RANK"),
    ("What is Toyota ARR in Q1FY26?", "LOOKUP"),
    ("ARR trend for Siemens AG over the last 4 quarters", "TREND"),
    ("How has Toyota's ARR moved quarter by quarter?", "TREND"),
    ("Compare ZIA and ZPA ARR in APJ for Q1FY26 vs Q4FY25", "COMPARE"),
    ("How much did Toyota's ZPA ARR grow in Q1FY26?", "DELTA"),
    ("What was the net ARR change for ZPA in EMEA in Q1FY26?", "DELTA"),
    ("Which accounts have the biggest downsell on ZIA in Q1FY26?", "RISK"),
    ("Is Toyota at risk of churn?", "RISK"),
    ("Break down ARR by product in FY26", "AGGREGATE"),                  # 'down' in 'break down' is not a decline
    ("Show ARR for all products in EMEA in Q1FY26", "AGGREGATE"),
]:
    check(q, intent=intent)

# ── regions, segments, products, accounts ────────────────────────────────────
check("ZIA ARR for French accounts Q1FY26", geo=["French"], products=["ZIA"])
check("ZPA ARR in Germany Q1FY26", geo=["Germany"])
check("ZPA ARR in APAC", geo=["APAC"])
check("ARR for Bank of America in Q1FY26", account="Bank of America", geo=[])      # no region from a company name
check("ARR for enterprise and large enterprise accounts in Q1FY26", segment=["large enterprise", "enterprise"])
check("Show me ARR for Public Sector accounts", segment=["Public Sector"])
check("SWG ARR Q1FY26", products=["SWG"])
check("What is the Private Access ARR in EMEA?", products=["Private Access"])
check("Zscaler total ARR in FY26", account=None)                              # the platform owner is not a customer
check("Show me ARR for Toyota Q1FY26, reviewed with Marco on Monday", account="Toyota")   # names outside a company slot
check("ARR for Monday Q1FY26", account="Monday")      # in a company slot: S2 will answer "company not found"
check("What is the ARR for Shell in Q1FY26", account="Shell")
check("Shell ARR Q1FY26", account="Shell")                                    # company as the first word still works

# ── period ───────────────────────────────────────────────────────────────────
for q, fiscal in [
    ("ZPA ARR in Q1FY26", "Q1FY26"), ("ZPA ARR in Q1 FY26", "Q1 FY26"), ("ZPA ARR in FY26", "FY26"),
    ("ZPA ARR in FY 2026 Q1", "FY 2026 Q1"), ("ZPA ARR last quarter", "last quarter"),
    ("ZPA ARR this quarter", "this quarter"), ("ZPA ARR for the last 6 quarters", "last 6 quarters"),
    ("ZPA ARR year to date", "year to date"), ("Compare ARR Q1FY25 and Q1FY26", "Q1FY25 and Q1FY26"), ("ZCP ARR trend FY25 to FY26", "FY25 to FY26"),
    ("Compare ARR Q1FY26 vs Q1FY25 for top accounts", "Q1FY26 vs Q1FY25"),
    ("ZPA ARR", None),
]:
    check(q, fiscal=fiscal)
check("ZPA ARR for the last 4 Quarters", fiscal="last 4 Quarters")     # kept exactly as typed

print("s1 rule-based extractor: all checks passed")
