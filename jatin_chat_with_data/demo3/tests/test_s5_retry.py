"""A retry prompt carries the failed SQL together with its validation errors. No network. Run: python3 tests/test_s5_retry.py"""
import contextlib
import io
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import s5_generate  # noqa: E402
from pipeline.models import Intent, SQLContext  # noqa: E402

BAD = ("SELECT end_user_name, SUM(arr) AS total_arr FROM data_arr "
       "WHERE fiscal_quarter = 'FY 2026 Q1' AND fiscal_year = 'FY 2026' GROUP BY end_user_name LIMIT 10;")
GOOD = ("SELECT end_user_name, SUM(arr) AS total_arr FROM data_arr "
        "WHERE fiscal_quarter = 'FY 2026 Q1' GROUP BY end_user_name LIMIT 10;")
ctx = SQLContext(normalized_question="q", intent=Intent.AGGREGATE, schema_ddl="",
                 where_values={"fiscal_quarter": "FY 2026 Q1"}, group_by=["end_user_name"])

prompts, replies = [], iter([BAD, GOOD])

def fake_post(url, headers, json, timeout):
    prompts.append(json["messages"][1]["content"])
    resp = mock.Mock(text="x")
    resp.json.return_value = {"choices": [{"message": {"content": next(replies)}}]}
    return resp

with mock.patch.object(s5_generate.requests, "post", side_effect=fake_post), contextlib.redirect_stdout(io.StringIO()):
    out = s5_generate.generate(ctx)

assert out.source == "llm" and out.attempts == 2
assert "Previous attempt failed" not in prompts[0]
assert BAD in prompts[1] and "V8 Extra WHERE filter on 'fiscal_year'" in prompts[1]   # failed SQL + its error
assert "Your previous SQL:" in prompts[1]
print("s5 retry: failed SQL and its errors are sent on the next attempt")


# ── regression: a WITH (CTE) query is valid, and a truncated reply is reported as truncation ──
CTE = ("WITH q AS (SELECT end_user_name, SUM(arr) AS v FROM data_arr WHERE fiscal_quarter = 'FY 2026 Q1' "
       "GROUP BY end_user_name) SELECT end_user_name, v FROM q ORDER BY v DESC LIMIT 10;")
assert s5_generate.validate(CTE, ctx) == []                       # 'q' is a CTE, not an unknown table
assert any("V2 Unknown table 'nope'" in e for e in s5_generate.validate(CTE.replace("FROM q ", "FROM nope "), ctx))

replies2, prompts2 = iter([("length", "WITH q AS (SELECT end_user_name, ABS(total_"), ("stop", GOOD)]), []

def fake_post2(url, headers, json, timeout):
    prompts2.append((json["max_tokens"], json["messages"][1]["content"]))
    finish, text = next(replies2)
    resp = mock.Mock(text="x")
    resp.json.return_value = {"choices": [{"finish_reason": finish, "message": {"content": text}}]}
    return resp

with mock.patch.object(s5_generate.requests, "post", side_effect=fake_post2), contextlib.redirect_stdout(io.StringIO()):
    out = s5_generate.generate(ctx)
assert out.source == "llm" and out.attempts == 2 and prompts2[0][0] >= 1500
assert "cut off" in prompts2[1][1] and "V1 Syntax" not in prompts2[1][1]   # told it was truncated, not given a bogus syntax error
print("s5: CTE names accepted; truncation detected")
