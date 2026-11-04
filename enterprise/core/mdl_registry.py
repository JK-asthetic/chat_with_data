"""MDL Registry — loads metrics.yaml and joins with MDL table definitions

to produce a fully-resolved MetricDefinition used by all metric agents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
import yaml

from core.mdl import CATALOG, TableDef

_ROOT = Path(__file__).parent.parent
_METRICS_CONFIG = _ROOT / "config" / "metrics.yaml"


@dataclass
class MetricDefinition:
    """Fully resolved metric — combines metrics.yaml + MDL TableDef."""

    name: str
    display_name: str
    description: str
    table: str
    value_column: str
    aggregation: str  # SUM | AVG | COUNT
    variant: str  # snapshot | delta | downsell | target | nnacv
    agent_class_path: str  # e.g. "agents.arr_agent.ARRAgent"
    keywords: list[str] = field(default_factory=list)
    id_columns: list[str] = field(default_factory=list)
    snapshot_date_column: Optional[str] = None
    always_filters: dict[str, Any] = field(default_factory=dict)
    filter_columns: dict[str, str] = field(default_factory=dict)
    sql_rules: list[str] = field(default_factory=list)
    table_def: Optional[TableDef] = field(default=None, repr=False)

    def schema_ddl(self, include_tiers: tuple[int, ...] = (1, 2)) -> str:
        if self.table_def:
            return self.table_def.ddl(include_tiers)
        return f"-- Table: {self.table} (definition not found in MDL)"


def load_metrics() -> dict[str, MetricDefinition]:
    if not _METRICS_CONFIG.exists():
        return {}

    raw: dict[str, Any] = yaml.safe_load(_METRICS_CONFIG.read_text(encoding="utf-8")) or {}
    metrics_map = raw.get("metrics", raw)

    registry: dict[str, MetricDefinition] = {}

    for metric_name, m in metrics_map.items():
        if not isinstance(m, dict) or metric_name.startswith("_") or metric_name == "version":
            continue

        table_name = m.get("table", "data_arr")
        table_def = CATALOG.get(table_name)

        defn = MetricDefinition(
            name=metric_name,
            display_name=m.get("display_name", metric_name),
            description=m.get("description", "").strip(),
            table=table_name,
            value_column=m.get("value_column", "arr"),
            aggregation=m.get("aggregation", "SUM").upper(),
            variant=m.get("variant", "snapshot"),
            agent_class_path=m.get("agent_class", f"agents.{metric_name.lower()}_agent.{metric_name}Agent"),
            keywords=m.get("keywords", []),
            id_columns=m.get("id_columns", []),
            snapshot_date_column=m.get("snapshot_date_column"),
            always_filters=m.get("always_filters", {}),
            filter_columns=m.get("filter_columns", {}),
            sql_rules=m.get("sql_rules", []),
            table_def=table_def,
        )
        registry[metric_name] = defn

    return registry


@lru_cache(maxsize=1)
def get_registry() -> dict[str, MetricDefinition]:
    return load_metrics()

