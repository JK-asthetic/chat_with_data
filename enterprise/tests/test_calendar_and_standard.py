"""Fiscal calendar, month parsing and the standard metric SQL (no DB, no LLM)."""
from datetime import date

from core import fiscal_calendar as cal
from sql.standard import NU_FILTER, Plan, build, reference

FQ = "FY 2027 Q1"


def test_quarter_bounds_and_labels_match_the_db():
    q = (2027, 1)
    assert (cal.quarter_start(q), cal.quarter_end(q)) == (date(2026, 8, 1), date(2026, 10, 31))
    assert cal.last_month_start(q) == date(2026, 10, 1)
    assert cal.arr_month_label(q) == "FY 2027 Q1 OCT"
    assert cal.arr_month_label((2027, 2)) == "FY 2027 Q2 JAN"
    assert cal.quarter_of(date(2026, 11, 5)) == (2027, 2)


def test_last_complete_quarter_and_trailing_window():
    assert cal.label(cal.last_complete_quarter(date(2026, 11, 5))) == "FY 2027 Q1"
    trail = [cal.label(q) for q in cal.trailing((2027, 1), 8)]
    assert trail[0] == "FY 2025 Q2" and trail[-1] == "FY 2027 Q1" and len(trail) == 8


def test_relative_range_ends_at_last_closed_quarter():
    rng = ["FY 2026 Q3", "FY 2026 Q4", "FY 2027 Q1", "FY 2027 Q2"]
    assert cal.clamp_range(rng, (2027, 1)) == ["FY 2026 Q2", "FY 2026 Q3", "FY 2026 Q4", "FY 2027 Q1"]


def test_month_parsing():
    today = date(2026, 11, 5)
    assert cal.find_month("ARR in October 2026", today) == date(2026, 10, 1)
    assert cal.find_month("ARR in Oct FY27", today) == date(2026, 10, 1)
    assert cal.find_month("ARR in Jan FY27", today) == date(2027, 1, 1)
    assert cal.find_month("ZIA qty in September", today) == date(2026, 9, 1)
    assert cal.find_month("we may need ARR", today) is None


def _where():
    return {
        "data_acv": {"fiscal_quarter": FQ},
        "data_inc_arr": {"aggregation_level": "Level L3", "fiscal_quarter": FQ},
        "data_nacv_target": {"fiscal_quarter": FQ},
        "data_pippeline_curr": {"opp_close_qtr": "FY 2027 Q2"},
        "data_renewal_risk": {"max_fiscal_month_flag": 1, "renewal_qtr": "FY 2027 Q3"},
        "data_quantity": {"fiscal_quarter": FQ, "fiscal_month": "2026-10-01"},
        "data_arr": {"fiscal_quarter": FQ},
        "t3_arr_detail": {"fiscal_quarter": FQ},
    }


def test_definitions_are_never_dropped():
    w = _where()
    assert NU_FILTER in build(Plan("NU_ACV", w, "product"))
    churn = build(Plan("CHURN", w, "product"))
    assert "'Customer Churn','ARR Churn'" in churn and "Level L3" in churn and "swap_positive + swap_negative" in churn
    nn = build(Plan("NNACV", w, "total"))
    assert NU_FILTER in nn and "Level L3" in nn and "nnacv" in nn and "FULL JOIN" not in nn      # total = cross of two 1-row CTEs
    assert "FULL JOIN" in build(Plan("NNACV", w, "product"))
    assert "max_fiscal_month_flag = 1" in build(Plan("RENEWAL_RISK", w, "product"))
    assert "'6 - Closed Won','7 - Closed Lost'" in build(Plan("OPEN_PIPELINE", w, "product"))
    assert "lower(trim(deployed_status))" in build(Plan("UNDEPLOYED_ARR", w, "product", level=3))
    assert "NULLIF" in build(Plan("ARPU", w, "product"))


def test_every_standard_query_has_a_limit_and_reference_lists_cuts():
    w = _where()
    for metric in ("NU_ACV", "ACV", "CHURN", "NNACV", "NACV", "OPEN_PIPELINE", "RENEWAL_RISK", "QTY", "ARPU", "ATTACH_RATE", "UNDEPLOYED_ARR"):
        assert " LIMIT " in build(Plan(metric, w, "total" if metric not in ("NACV", "ATTACH_RATE", "UNDEPLOYED_ARR") else "product")).upper()
    ref = reference(Plan("NU_ACV", w, "product"), ["product", "account", "parent"])
    assert ref.count("-- cut:") == 3
