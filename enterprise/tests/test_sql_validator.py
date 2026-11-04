"""Unit tests for SQL validation rules."""
import pytest
from pipeline.models import SQLContext, Intent
from sql.validator import validate


@pytest.fixture
def base_ctx():
    return SQLContext(
        normalized_question="top 10 arr in emea",
        intent=Intent.RANK,
        metric="arr",
        metric_name="ARR",
        primary_table="data_arr",
    )


def test_validator_clean_query(base_ctx):
    sql = "SELECT account_id, end_user_name, SUM(arr) AS total_arr FROM data_arr WHERE cfy_geo = 'EMEA' GROUP BY account_id, end_user_name LIMIT 10;"
    errors = validate(sql, base_ctx)
    assert len(errors) == 0


def test_validator_catches_mutation(base_ctx):
    sql = "DELETE FROM data_arr WHERE account_id = '123' LIMIT 10;"
    errors = validate(sql, base_ctx)
    assert any("Mutation" in e for e in errors)


def test_validator_catches_unknown_table(base_ctx):
    sql = "SELECT * FROM non_existent_table LIMIT 10;"
    errors = validate(sql, base_ctx)
    assert any("Unknown table" in e for e in errors)


def test_validator_catches_wrong_geo_column_on_data_arr(base_ctx):
    sql = "SELECT end_user_name, SUM(arr) FROM data_arr WHERE geo = 'EMEA' GROUP BY end_user_name LIMIT 10;"
    errors = validate(sql, base_ctx)
    assert any("cfy_geo" in e for e in errors)


def test_validator_catches_missing_limit(base_ctx):
    sql = "SELECT account_id, end_user_name, SUM(arr) FROM data_arr GROUP BY account_id, end_user_name;"
    errors = validate(sql, base_ctx)
    assert any("LIMIT" in e for e in errors)

