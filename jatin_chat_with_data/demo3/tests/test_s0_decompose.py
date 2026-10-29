"""S0 rule-based decomposition + session memory + dependent binding (no network, no database, no model).
Run: python3 tests/test_s0_decompose.py
"""
import sys
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fixtures  # noqa: E402
from core import companies  # noqa: E402
from core.memory import SessionMemory, Turn  # noqa: E402
from pipeline import s0_decompose as s0  # noqa: E402
from pipeline import s1_extract  # noqa: E402
from pipeline.models import SubQuery  # noqa: E402

fixtures.install_hierarchy()
KNOWN = {"toyota", "bmw", "siemens", "siemens ag", "microsoft", "google", "honda", "hsbc", "barclays"}
companies.existing = lambda cands, exact=False: {c.lower() for c in cands if c.lower() in KNOWN}   # hermetic account list


def texts(q, memory=None):
    p = s0.plan(q, memory)
    return p, [s.text for s in p.sub_queries]


# ── 'top N and bottom N <shared tail>': both halves must keep the tail (regression: left half was 'Show me top 10') ──
p, t = texts("Show me top 10 and bottom 10 accounts by Private Access ARR in EMEA Q1FY26.")
assert p.strategy == "split" and len(t) == 2, t
assert t[0].lower().startswith("show me top 10 accounts by private access arr in emea q1fy26"), t
assert t[1].lower().startswith("bottom 10 accounts by private access arr in emea q1fy26"), t

# ── one question stays one question (single-intent shapes that merely contain 'and') ──
WHOLE = [
    "What is the total ARR for ZPA in EMEA in Q1FY26?",
    "Top 10 accounts by ARR in EMEA for FY 2026 Q1",
    "Compare ZIA and ZPA ARR in APJ for Q1FY26 vs Q4FY25",                       # compare = one intent
    "ZPA ARR trend for Siemens AG by quarter in FY26",                            # trend = one intent
    "What is the total ARR for ZPA in EMEA, APJ and Americas in Q1FY26?",         # list of regions = one ask
    "Show ARR for ZIA and ZPA in Q1FY26",                                         # two products = one ask
    "Take the top 20 accounts by ARR in Q1FY26 and compare their Q1FY26 ARR vs Q1FY25 ARR.",  # 'their' = the 20
    "Give me ARR trend for Private Access, enterprise account in EMEA for last 4 quarters",
]
for q in WHOLE:
    p, t = texts(q)
    assert p.strategy == "passthrough" and t == [" ".join(q.split())], (q, t)

# ── independent clauses ──────────────────────────────────────────────────────
p, t = texts("What is the total ZIA ARR in EMEA in Q1FY26 and what is the total ZPA ARR in APJ in Q1FY26?")
assert p.strategy == "split" and len(t) == 2 and "ZIA" in t[0] and "EMEA" in t[0] and "ZPA" in t[1] and "APJ" in t[1]
assert all(not s.depends_on for s in p.sub_queries)

p, t = texts("What is the total ARR for Digital Experience in Q1FY26, and who are the top 3 accounts for ZPA in Q1FY26?")
assert len(t) == 2 and "Digital Experience" in t[0] and "top 3" in t[1] and "ZPA" in t[1]

p, t = texts("Total ARR in Q1FY26, ZPA ARR in EMEA in Q1FY26, and the top 3 accounts in APJ in Q1FY26")
assert len(t) == 3 and "EMEA" in t[1] and "APJ" in t[2] and all("Q1FY26" in x for x in t), t

# ── dependent clause: 'its' after a singular-top clause ──────────────────────
p, t = texts("Who is the top account by ARR in EMEA in Q1FY26 and what is its ZPA ARR in Q1FY26?")
assert len(t) == 2 and p.sub_queries[1].depends_on == ["q1"] and "{{q1.account}}" in t[1] and "ZPA" in t[1]
assert [[s.id for s in w] for w in s0.order(p.sub_queries)] == [["q1"], ["q2"]]      # q2 runs in a later stage

# ── bare clause borrows scope; a clause with its own scope only borrows a missing period ──
p, t = texts("ARR for Siemens AG in Q1FY26 and the growth")
assert len(t) == 2 and "Siemens AG" in t[1] and "Q1FY26" in t[1] and "rowth" in t[1], t
p, t = texts("ZPA ARR in EMEA enterprise Q1FY26 and the churn")
assert len(t) == 2 and "ZPA" in t[1] and "EMEA" in t[1] and "enterprise" in t[1] and "Q1FY26" in t[1], t
p, t = texts("What is the ZIA ARR in EMEA and what is the ZPA ARR in APJ in Q1FY26?")   # shared trailing period
assert len(t) == 2 and "Q1FY26" in t[0] and "Q1FY26" in t[1], t

# ── several companies: one part per company, connectors removed ──────────────
p, t = texts("Show me ARR for Toyota and BMW Q1FY26.")
assert len(t) == 2 and "Toyota" in t[0] and "BMW" not in t[0] and "BMW" in t[1] and "Toyota" not in t[1], t
p, t = texts("Give me Private Access ARR for Microsoft and Google Q1FY26.")
assert len(t) == 2 and "Microsoft" in t[0] and "Google" in t[1] and all("Private Access" in x for x in t), t
p, t = texts("Which has higher ARR — Siemens or Toyota in q1 2027")
assert len(t) == 2 and "Siemens" in t[0] and "Toyota" not in t[0] and "Toyota" in t[1], t
p, t = texts("ARR for Toyota, BMW and Honda in Q1FY26")
assert len(t) == 3 and [("Toyota" in x, "BMW" in x, "Honda" in x) for x in t] == [(1, 0, 0), (0, 1, 0), (0, 0, 1)], t
p, t = texts("ARR for Siemens AG in Q1FY26")                        # 'Siemens' inside 'Siemens AG' is ONE company
assert p.strategy == "passthrough"
KNOWN |= {"audi", "ford"}
p = s0.plan("ARR for Toyota, BMW, Honda, Audi and Ford in Q1FY26")  # five parts is over the limit of four
assert p.strategy == "passthrough" and len(p.sub_queries) == 1 and any("limit" in n for n in p.notes)
KNOWN -= {"audi", "ford"}

# ── invariant: every entity the user typed lands in some part (nothing silently dropped) ──
for q in ["What is the total ZIA ARR in EMEA in Q1FY26 and what is the total ZPA ARR in APJ in Q1FY26?",
          "Total ARR in Q1FY26, ZPA ARR in EMEA in Q1FY26, and the top 3 accounts in APJ in Q1FY26",
          "Show me ARR for Toyota and BMW Q1FY26.", "Which has higher ARR — Siemens or Toyota in q1 2027"]:
    typed = s1_extract.find_slots(q)
    parts = [s1_extract.find_slots(s.text) for s in s0.plan(q).sub_queries]
    for slot in ("accounts", "products", "geo", "segments"):
        got = {v.lower() for sl in parts for v in sl[slot]}
        assert {v.lower() for v in typed[slot]} <= got, (q, slot, typed[slot], got)
    if typed["fiscal"]:
        assert any(sl["fiscal"] for sl in parts), q

# ── dependency ordering: any order is accepted; waves group independent parts ──
shuffled = [SubQuery(id="q2", text="b {{q1.account}}", depends_on=["q1"]), SubQuery(id="q3", text="c"),
            SubQuery(id="q1", text="a")]
assert [sorted(s.id for s in w) for w in s0.order(shuffled)] == [["q1", "q3"], ["q2"]]
assert s0.order([SubQuery(id="q1", text="a", depends_on=["q2"]), SubQuery(id="q2", text="b", depends_on=["q1"])]) is None

# ── a splitter bug never blocks a question ───────────────────────────────────
with mock.patch.object(s0, "_decompose", side_effect=RuntimeError("boom")):
    p = s0.plan("What is the total ARR for ZPA in Q1FY26?")
assert p.strategy == "passthrough" and "unchanged" in p.notes[-1]

# ── session memory: references resolve from stored rows, never guessed ───────
mem = SessionMemory()
assert s0.plan("What is the second one's ZIA ARR?", mem).strategy == "passthrough"   # empty memory: nothing to resolve
mem.add(Turn("top 3", "Top 3 accounts by ZPA ARR in EMEA in Q1FY26", {"geo": ["EMEA"], "products": ["ZPA"]},
             ["end_user_name", "total_arr"],
             [{"end_user_name": n, "total_arr": 1} for n in ("Alpha AG", "Beta plc", "Gamma SA")]))
text, notes, unresolved = mem.resolve_references("What is the second one's ZIA ARR in Q1FY26?")
assert text == "What is Beta plc's ZIA ARR in Q1FY26?" and not unresolved and notes
assert mem.resolve_references("how is the last account doing")[0] == "how is Gamma SA doing"
_, _, un = mem.resolve_references("What about the fifth one?")
assert un and "3 account" in un[0]
_, _, un = mem.resolve_references("What is that account's ARR?")      # last result listed three accounts
assert un
text, _, un = mem.resolve_references("Who is the top account by ARR in EMEA?")   # fresh question, 'top' is not a reference
assert text == "Who is the top account by ARR in EMEA?" and not un
p = s0.plan("What about the fifth one?", mem)
assert p.unresolved and not p.sub_queries                       # asks instead of guessing
p = s0.plan("What is the third one's ZIA ARR in Q1FY26?", mem)
assert p.strategy == "followup" and p.sub_queries[0].text == "What is Gamma SA's ZIA ARR in Q1FY26?"

big = SessionMemory()                                           # memory stays small: capped turns and rows
for i in range(20):
    big.add(Turn("q", f"question {i}", {}, ["end_user_name"], [{"end_user_name": str(j)} for j in range(50)]))
assert len(big.turns) == 6 and all(len(t.rows) == 10 for t in big.turns)

# ── dependent binding (main._bind) uses the real result row ─────────────────
import main  # noqa: E402
from pipeline.models import QueryResult  # noqa: E402


class _R:  # minimal stand-in for PipelineResponse
    def __init__(self, columns, rows):
        self.result = QueryResult(sql="", columns=columns, rows=rows, row_count=len(rows), success=True)


done = {"q1": main.PartOutcome(id="q1", text="x", response=_R(["end_user_name", "total_arr"],
                                                                [{"end_user_name": "Alpha AG", "total_arr": 9}]))}
assert main._bind("What is {{q1.account}} ZPA ARR in Q1FY26?", done) == "What is Alpha AG ZPA ARR in Q1FY26?"
assert main._bind("no placeholder", done) == "no placeholder"
for bad_done in ({}, {"q1": main.PartOutcome(id="q1", text="x")},
                 {"q1": main.PartOutcome(id="q1", text="x", response=_R(["end_user_name"], []))},
                 {"q1": main.PartOutcome(id="q1", text="x", response=_R(["product_l1"], [{"product_l1": "ZPA"}]))}):
    try:
        main._bind("{{q1.account}}", bad_done)
        raise AssertionError("expected _Unbound")
    except main._Unbound:
        pass

# ── S7: money is formatted in code before the LLM sees it (regression: $94.8K was reported as $94.8M) ──
from pipeline import s7_respond  # noqa: E402

h = s7_respond.humanize_rows([{"end_user_name": "AstraZeneca", "total_arr": Decimal("94819.7916"), "rank": 3}])
assert h == [{"end_user_name": "AstraZeneca", "total_arr": "$94.8K", "rank": 3}]
assert s7_respond.humanize_rows([{"arr": 219920803.63956}])[0]["arr"] == "$219.9M"

print("s0 / memory / binding tests passed")
