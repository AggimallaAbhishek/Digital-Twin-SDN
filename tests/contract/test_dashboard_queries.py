"""P2.2 contract: every measurement and field the Grafana dashboard queries is one the collector
writes (common/schemas.py via telemetry/collector/records.py). Catches silent panel breakage
when a schema field or measurement is renamed."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from common.schemas import MEASUREMENTS
from telemetry.collector.records import RUN_TAGS, TAGS

DASHBOARD = Path(__file__).resolve().parents[2] / "telemetry/grafana/dashboards/raw_kpis.json"
PANELS = [p for p in json.loads(DASHBOARD.read_text())["panels"] if "targets" in p]
MODELS = {name: model for model, name in MEASUREMENTS.items()}
_MEASUREMENT = re.compile(r'r\._measurement == "(\w+)"')
_FIELD = re.compile(r'r\._field == "(\w+)"')


def _query(panel: dict[str, Any]) -> str:
    return str(panel["targets"][0]["query"])


@pytest.mark.parametrize("panel", PANELS, ids=lambda p: p["title"])
def test_panel_queries_known_measurements_and_fields(panel: dict[str, Any]) -> None:
    query = _query(panel)
    measurements = _MEASUREMENT.findall(query)
    assert measurements, "every panel filters on a measurement"
    for measurement in measurements:
        assert measurement in MODELS, f"unknown measurement {measurement!r}"
        model = MODELS[measurement]
        stored_fields = set(model.model_fields) - {"ts", *TAGS[model], *RUN_TAGS}
        for field in _FIELD.findall(query):
            assert field in stored_fields, f"{measurement} has no field {field!r}"


@pytest.mark.parametrize("panel", PANELS, ids=lambda p: p["title"])
def test_panel_is_scoped_to_the_selected_run(panel: dict[str, Any]) -> None:
    assert 'r.run_id == "${run_id}"' in _query(panel)
