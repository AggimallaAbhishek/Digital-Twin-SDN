"""P1.3 contract: real AP agent responses (recorded on the VM) fit common/schemas.py.

Fixtures come from testbed/checks/ap_agent_check.py (`make ap-agent-vm`, 2026-10-07). The mapping
below is the contract the collector (P2.1) must implement: agent records + run metadata ->
schema records. /aps/{ap}/stats records carry their own `ts`; /stations records take the
response's top-level `ts`.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from common.schemas import APStats, StationStats

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ap_agent"
META = {"scenario_id": "fixture", "run_id": "ap_agent_check"}
EXPECTED_APS = 4
EXPECTED_STATIONS = 20


def _load(name: str) -> Any:
    return json.loads((FIXTURES / f"ap_agent_{name}.json").read_text())


AP_STATS = _load("ap_stats")["aps"]
STATIONS = _load("stations")
APS = _load("aps")["aps"]


@pytest.mark.parametrize("record", AP_STATS, ids=lambda r: r["ap"])
def test_ap_stats_records_validate_as_ap_stats(record: dict[str, Any]) -> None:
    APStats.model_validate({**record, **META})


@pytest.mark.parametrize("record", STATIONS["stations"], ids=lambda r: r["sta"])
def test_station_records_validate_as_station_stats(record: dict[str, Any]) -> None:
    StationStats.model_validate({**record, "ts": STATIONS["ts"], **META})


def test_fixtures_cover_the_whole_campus() -> None:
    assert len(AP_STATS) == len(APS) == EXPECTED_APS
    assert len(STATIONS["stations"]) == EXPECTED_STATIONS
    assert all(s["ap"] for s in STATIONS["stations"])


def test_ap_list_agrees_with_ap_stats() -> None:
    stats = {r["ap"]: r for r in AP_STATS}
    for ap in APS:
        assert (ap["channel"], ap["tx_power_dbm"]) == (
            stats[ap["ap"]]["channel"],
            stats[ap["ap"]]["tx_power_dbm"],
        )
