"""P1.5 contract: real KPI probe records (recorded on the VM) fit common/schemas.py KPIRecord.

Fixtures come from testbed/checks/traffic_check.py (`make traffic-vm`, 2026-10-07): every record
of a 30 s run (kpi_records.jsonl) and the AP agent's GET /kpi response (kpi_response.json). The
collector (P2.1) adds scenario_id and run_id, the same as for the agent's other records.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from common.schemas import KPIRecord

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "traffic"
META = {"scenario_id": "fixture", "run_id": "traffic_check"}
FLOWS = {"sta1-video", "sta16-video", "sta4-bulk", "sta9-web"}

RECORDS: list[dict[str, Any]] = [
    json.loads(line) for line in (FIXTURES / "kpi_records.jsonl").read_text().splitlines()
]
RESPONSE: dict[str, Any] = json.loads((FIXTURES / "kpi_response.json").read_text())


@pytest.mark.parametrize("record", RECORDS, ids=lambda r: f"{r['flow_id']}@{r['ts'][11:19]}")
def test_probe_records_validate_as_kpi_records(record: dict[str, Any]) -> None:
    KPIRecord.model_validate({**record, **META})


@pytest.mark.parametrize("record", RESPONSE["kpis"], ids=lambda r: r["flow_id"])
def test_kpi_endpoint_records_validate_as_kpi_records(record: dict[str, Any]) -> None:
    KPIRecord.model_validate({**record, **META})


def test_fixtures_cover_every_profile_and_flow() -> None:
    assert {r["flow_id"] for r in RECORDS} == FLOWS
    assert {r["app_class"] for r in RECORDS} == {"video", "bulk", "web"}
    assert {r["flow_id"] for r in RESPONSE["kpis"]} == FLOWS


def test_flow_id_names_station_and_class() -> None:
    for record in RECORDS:
        sta, app_class = record["flow_id"].split("-")
        assert app_class == record["app_class"]
        assert sta.startswith("sta")
