"""Runner for all unit tests using standard library unittest."""
import sys
import unittest
from pathlib import Path

# Add project root to path
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from datetime import date
from extraction.tools.fiscal_tool import _parse_fiscal_raw, quarter_of
from extraction.tools.geo_tool import resolve_geo
from extraction.tools.segment_tool import resolve_segments
from extraction.tools.order_type_tool import resolve_order_types
from core.mdl_registry import get_registry
from core.mdl import CATALOG
from sql.validator import validate
from pipeline.models import SQLContext, Intent
import asyncio


class TestEnterprisePipeline(unittest.TestCase):
    def test_metrics_registry(self):
        reg = get_registry()
        self.assertGreaterEqual(len(reg), 7)
        for m in ("ARR", "ACV", "INCR_ARR", "CHURN", "NACV", "QTY"):
            self.assertIn(m, reg)
            self.assertIn(reg[m].table, CATALOG)

    def test_fiscal_parsing(self):
        f = _parse_fiscal_raw("Q1FY26")
        self.assertEqual(f.fiscal_quarter_label, "FY 2026 Q1")
        self.assertEqual(f.fiscal_year_label, "FY 2026")

        f_range = _parse_fiscal_raw("Q1FY26 vs Q3FY26")
        self.assertTrue(f_range.is_range)
        self.assertEqual(len(f_range.quarter_labels), 2)

    def test_quarter_of(self):
        fy, fq = quarter_of(date(2026, 9, 15))
        self.assertEqual(fy, "FY 2027")
        self.assertEqual(fq, "FY 2027 Q1")

    def test_geo_resolution(self):
        res, inv = asyncio.run(resolve_geo(["EMEA"]))
        self.assertIn("EMEA", res)
        self.assertEqual(len(inv), 0)

        res2, _ = asyncio.run(resolve_geo(["Americas"]))
        self.assertTrue("AMS ECE" in res2 or "AMS MPH" in res2)

    def test_segment_resolution(self):
        res, _ = asyncio.run(resolve_segments(["ENT"]))
        self.assertIn("Enterprise", res)

    def test_order_type_resolution(self):
        res = asyncio.run(resolve_order_types(["new logo"]))
        self.assertIn("NEW_CUST", res)

    def test_sql_validator(self):
        ctx = SQLContext(
            normalized_question="top 10 arr",
            intent=Intent.RANK,
            metric="arr",
            metric_name="ARR",
            primary_table="data_arr",
        )
        # Valid query
        clean_sql = "SELECT account_id, end_user_name, SUM(arr) FROM data_arr GROUP BY account_id, end_user_name LIMIT 10;"
        errs = validate(clean_sql, ctx)
        self.assertEqual(len(errs), 0)

        # Mutation query
        del_sql = "DELETE FROM data_arr WHERE account_id = '123' LIMIT 10;"
        del_errs = validate(del_sql, ctx)
        self.assertTrue(any("Mutation" in e for e in del_errs))

        # Unknown table query
        unk_sql = "SELECT * FROM ghost_table LIMIT 10;"
        unk_errs = validate(unk_sql, ctx)
        self.assertTrue(any("Unknown table" in e for e in unk_errs))


if __name__ == "__main__":
    unittest.main(verbosity=2)

