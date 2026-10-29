"""Live end-to-end eval: S0 split -> S1..S6 -> answers checked against independent SQL on data_arr.

Needs Ollama (S1), ZLLAMA (S0/S5/S7) and the database. Not part of the hermetic tests.
Run: python3 tests/eval_multiquery.py            # all cases
     python3 tests/eval_multiquery.py c3 f1      # selected case ids

A part that would need an interactive clarification is reported as NEEDS-CLARIFICATION (a failure here:
every eval question is fully specified). Ground truth is plain SQL below, never the pipeline's own output.
"""
import asyncio
import builtins
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from pipeline import s2_resolve  # noqa: E402
from core.db import query_all  # noqa: E402
from core.memory import SessionMemory  # noqa: E402

Q1 = "FY 2026 Q1"


def _no_input(*_a, **_k):
    raise EOFError  # run_multi turns this into NEEDS-CLARIFICATION


builtins.input = _no_input


# ── ground truth (independent of the pipeline) ───────────────────────────────
def truth_sum(product=None, geo=None, account=None, quarter=Q1):
    where, params = ["fiscal_quarter = %(q)s"], {"q": quarter}
    if product:
        where.append("product_l1 = %(p)s"); params["p"] = product
    if geo:
        where.append("end_user_parent_geo = %(g)s"); params["g"] = geo
    if account:
        where.append("end_user_name = %(a)s"); params["a"] = account
    return float(query_all(f"SELECT COALESCE(SUM(arr),0) AS v FROM data_arr WHERE {' AND '.join(where)}", params)[0]["v"])


def truth_rank(n, product=None, geo=None, quarter=Q1):
    where, params = ["fiscal_quarter = %(q)s"], {"q": quarter}
    if product:
        where.append("product_l1 = %(p)s"); params["p"] = product
    if geo:
        where.append("end_user_parent_geo = %(g)s"); params["g"] = geo
    rows = query_all(f"SELECT end_user_name AS n, SUM(arr) AS v FROM data_arr WHERE {' AND '.join(where)} "
                     f"GROUP BY end_user_name ORDER BY v DESC, n LIMIT {int(n)}", params)
    return [(r["n"], float(r["v"])) for r in rows]


# ── result readers ───────────────────────────────────────────────────────────
def arr_col(cols):
    return next((c for c in cols if "arr" in c.lower()), None)


def scalar(part):
    res = part.response.result
    col = arr_col(res.columns)
    return sum(float(r[col]) for r in res.rows) if col else None


def ranking(part):
    res = part.response.result
    ncol, vcol = main.account_column(res.columns), arr_col(res.columns)
    return [(r[ncol], float(r[vcol])) for r in res.rows]


def close(a, b, tol=0.005):
    return a is not None and abs(a - b) <= tol * max(abs(b), 1.0)


def check_scalar(expected):
    def f(part):
        got = scalar(part)
        return (close(got, expected), f"got {got}, expected {expected:,.0f}")
    return f


def check_rank(expected):
    def f(part):
        got = ranking(part)
        names_ok = [g[0] for g in got] == [e[0] for e in expected]
        vals_ok = names_ok and all(close(g[1], e[1]) for g, e in zip(got, expected))
        return (vals_ok, f"got {[g[0] for g in got]}, expected {[e[0] for e in expected]}")
    return f


def expect_clarification(part):  # handled in run_case: the part must NOT produce an answer
    return (False, "answered although the account is ambiguous")


def check_ok(part):
    return (part.response.result.row_count > 0, f"{part.response.result.row_count} rows")


# ── cases: (id, label, [turns]); a turn = (question, expected_parts, [part checks or None]) ──
def resolves_cleanly(name):
    matches, ambiguous = asyncio.run(s2_resolve._tool_account(name))
    return bool(matches) and not ambiguous


ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth"]
top_emea = truth_rank(1, geo="EMEA")[0][0]
zpa_emea6 = truth_rank(6, product="ZPA", geo="EMEA")
# A follow-up on a ranked name only works end to end if S2 can resolve that name to one account.
# Pick a clean one (not the first, so indexing is really exercised); an ambiguous one is tested in f4.
clean_i = next(i for i in range(1, 6) if resolves_cleanly(zpa_emea6[i][0]))
amb_i = next(i for i in range(6) if not resolves_cleanly(zpa_emea6[i][0]))
CASES = [
    ("s1", "simple: scalar", [("What is the total ARR for ZPA in EMEA in Q1FY26?", 1,
                               [check_scalar(truth_sum("ZPA", "EMEA"))])]),
    ("s2", "simple: top 5 ranking", [("Top 5 accounts by ARR in EMEA in Q1FY26", 1,
                                      [check_rank(truth_rank(5, geo="EMEA"))])]),
    ("s3", "must stay whole: compare periods", [("Compare ZIA and ZPA ARR in APJ for Q1FY26 vs Q4FY25", 1, [check_ok])]),
    ("s4", "must stay whole: two products, one ask", [("What is the total ARR for ZIA and ZPA in Q1FY26?", 1,
                                                       [check_scalar(truth_sum("ZIA") + truth_sum("ZPA"))])]),
    ("c1", "complex: two independent scalars",
     [("What is the total ZIA ARR in EMEA in Q1FY26 and what is the total ZPA ARR in APJ in Q1FY26?", 2,
       [check_scalar(truth_sum("ZIA", "EMEA")), check_scalar(truth_sum("ZPA", "APJ"))])]),
    ("c2", "complex: scalar + ranking",
     [("What is the total ARR for Digital Experience in Q1FY26, and who are the top 3 accounts for ZPA in Q1FY26?", 2,
       [check_scalar(truth_sum("Digital Experience")), check_rank(truth_rank(3, product="ZPA"))])]),
    ("c3", "complex: dependent (top account, then ITS ZPA ARR)",
     [("Who is the top account by ARR in EMEA in Q1FY26 and what is its ZPA ARR in Q1FY26?", 2,
       [check_rank(truth_rank(1, geo="EMEA")), check_scalar(truth_sum("ZPA", account=top_emea))])]),
    ("c4", "complex: three parts",
     [("Total ARR in Q1FY26, ZPA ARR in EMEA in Q1FY26, and the top 3 accounts in APJ in Q1FY26", 3,
       [check_scalar(truth_sum()), check_scalar(truth_sum("ZPA", "EMEA")), check_rank(truth_rank(3, geo="APJ"))])]),
    ("f1", f"follow-up: 'the {ORDINALS[clean_i]} one' from the previous result",
     [("Top 6 accounts by ZPA ARR in EMEA in Q1FY26", 1, [check_rank(zpa_emea6)]),
      (f"What is the {ORDINALS[clean_i]} one's ZIA ARR in Q1FY26?", 1,
       [check_scalar(truth_sum("ZIA", account=zpa_emea6[clean_i][0]))])]),
    ("f2", "follow-up: inherit product + period, swap region",
     [("What is the total ZPA ARR in EMEA in Q1FY26?", 1, [check_scalar(truth_sum("ZPA", "EMEA"))]),
      ("and for APJ?", 1, [check_scalar(truth_sum("ZPA", "APJ"))])]),
    ("f3", "follow-up: out-of-range reference asks instead of guessing",
     [("Top 6 accounts by ZPA ARR in EMEA in Q1FY26", 1, [check_rank(zpa_emea6)]),
      ("What is the tenth one's ZIA ARR in Q1FY26?", 0, [])]),
    ("f4", f"follow-up: ambiguous account ('the {ORDINALS[amb_i]} one') asks instead of guessing",
     [("Top 6 accounts by ZPA ARR in EMEA in Q1FY26", 1, [check_rank(zpa_emea6)]),
      (f"What is the {ORDINALS[amb_i]} one's ZIA ARR in Q1FY26?", 1, [expect_clarification])]),
]


def run_case(cid, label, turns):
    memory, problems, shown = SessionMemory(), [], []
    for question, n_parts, checks in turns:
        out = main.run_multi(question, memory, display=False)
        texts = [p.text for p in out.parts]
        shown.append(f"      Q: {question}\n         -> {out.plan.strategy}: {texts}")
        if n_parts == 0:
            if not out.plan.unresolved:
                problems.append("expected an unresolved reference, but the question ran")
            continue
        if len(out.parts) != n_parts:
            problems.append(f"expected {n_parts} part(s), got {len(out.parts)}")
            continue
        for p, chk in zip(out.parts, checks):
            if chk is expect_clarification:
                if p.response is not None:
                    problems.append(f"{p.id}: guessed an account instead of asking")
                elif "clarification" not in (p.error or ""):
                    problems.append(f"{p.id}: failed for the wrong reason — {p.error}")
                continue
            if p.response is None:
                problems.append(f"{p.id}: {p.error}" + (" [NEEDS-CLARIFICATION]" if "clarification" in (p.error or "") else ""))
                continue
            ok, why = chk(p)
            if not ok:
                problems.append(f"{p.id}: WRONG ANSWER — {why}")
    return problems, shown


if __name__ == "__main__":
    wanted = set(sys.argv[1:])
    results = []
    for cid, label, turns in CASES:
        if wanted and cid not in wanted:
            continue
        problems, shown = run_case(cid, label, turns)
        results.append((cid, label, problems))
        print(f"{'PASS' if not problems else 'FAIL'}  {cid}  {label}")
        print("\n".join(shown))
        for pr in problems:
            print(f"      ✗ {pr}")
        sys.stdout.flush()
    failed = [r for r in results if r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} cases passed")
    sys.exit(1 if failed else 0)
