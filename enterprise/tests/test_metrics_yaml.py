"""Validate metrics.yaml schema and MDL registry integration."""
import pytest
from core.mdl_registry import get_registry, MetricDefinition
from core.mdl import CATALOG


def test_metrics_registry_loads():
    reg = get_registry()
    assert len(reg) >= 7
    assert "ARR" in reg
    assert "ACV" in reg
    assert "INCR_ARR" in reg
    assert "CHURN" in reg
    assert "NACV" in reg
    assert "QTY" in reg


def test_every_metric_has_valid_table():
    reg = get_registry()
    for name, m in reg.items():
        assert m.table in CATALOG, f"Metric '{name}' points to unknown table '{m.table}'"
        assert m.table_def is not None


def test_metric_fields_complete():
    reg = get_registry()
    for name, m in reg.items():
        assert m.name == name
        assert m.display_name
        assert m.value_column
        assert m.aggregation in ("SUM", "AVG", "COUNT")
        assert m.agent_class_path

