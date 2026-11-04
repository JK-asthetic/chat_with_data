"""Unit tests for deterministic extraction tools."""
import pytest
from datetime import date
from extraction.tools.fiscal_tool import _parse_fiscal_raw, _parse_relative, quarter_of
from extraction.tools.geo_tool import resolve_geo
from extraction.tools.segment_tool import resolve_segments
from extraction.tools.order_type_tool import resolve_order_types


def test_fiscal_raw_parsing():
    f1 = _parse_fiscal_raw("Q1FY26")
    assert f1.fiscal_quarter_label == "FY 2026 Q1"
    assert f1.fiscal_year_label == "FY 2026"

    f2 = _parse_fiscal_raw("FY 2026")
    assert f2.fiscal_year_label == "FY 2026"

    f3 = _parse_fiscal_raw("Q1FY26 vs Q3FY26")
    assert f3.is_range is True
    assert len(f3.quarter_labels) == 2


def test_quarter_of():
    fy, fq = quarter_of(date(2026, 9, 15))
    assert fy == "FY 2027"
    assert fq == "FY 2027 Q1"


@pytest.mark.asyncio
async def test_geo_resolution():
    res, invalid = await resolve_geo(["EMEA"])
    assert "EMEA" in res
    assert not invalid

    res2, _ = await resolve_geo(["Americas"])
    assert "AMS ECE" in res2 or "AMS MPH" in res2


@pytest.mark.asyncio
async def test_segment_resolution():
    res, _ = await resolve_segments(["ENT"])
    assert "Enterprise" in res


@pytest.mark.asyncio
async def test_order_type_resolution():
    res = await resolve_order_types(["new logo"])
    assert "NEW_CUST" in res

