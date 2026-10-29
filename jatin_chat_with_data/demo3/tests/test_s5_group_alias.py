"""GROUP BY <alias> on a computed column is pinned to its position, so a same-named real column cannot hijack it.
Run: python3 tests/test_s5_group_alias.py
"""
import sys
from pathlib import Path

import sqlglot

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import s5_generate  # noqa: E402

FAILED = """SELECT
    CASE
        WHEN product_l1 = 'ZIA' THEN 'Internet Access'
        WHEN product_l1 = 'ZPA' THEN 'Private Access'
    END AS product_category,
    SUM(arr) AS total_arr
FROM data_arr
WHERE fiscal_quarter = 'FY 2026 Q1' AND account_id = '0017000000j93aJAAQ'
GROUP BY product_category
LIMIT 1000;"""

fixed = s5_generate.pin_group_by_aliases(FAILED)
group = sqlglot.parse_one(fixed, dialect="postgres").args["group"]
assert [g.sql() for g in group.expressions] == ["1"], fixed        # the alias is now the select position
assert "AS product_category" in fixed and "SUM(arr)" in fixed       # the select list is unchanged

PLAIN = "SELECT end_user_name, SUM(arr) AS total_arr FROM data_arr GROUP BY end_user_name LIMIT 10;"
assert s5_generate.pin_group_by_aliases(PLAIN) == PLAIN             # plain column groups are never touched

NO_GROUP = "SELECT SUM(arr) AS total_arr FROM data_arr LIMIT 10;"
assert s5_generate.pin_group_by_aliases(NO_GROUP) == NO_GROUP
assert s5_generate.pin_group_by_aliases("SELECT FROM WHERE (") == "SELECT FROM WHERE ("   # unparsable: left for V1

print("ok")
