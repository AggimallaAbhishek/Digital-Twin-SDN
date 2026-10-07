"""P1.2 contract: real Ryu REST responses (recorded on the VM) fit common/schemas.py.

Fixtures come from testbed/checks/controller_check.py (`make controller-vm`, 2026-10-07); the flow
fixture is trimmed to 40 representative records. The mapping below is the contract the collector
(P2.1) must implement: controller records + run metadata -> schema records.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from common.schemas import FlowStats, PortStats

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ryu"
META = {"scenario_id": "fixture", "run_id": "controller_check"}
FLOW_FIELDS = ("ts", "dpid", "flow_id", "bytes", "pkts", "duration_s", "bps")
EXPECTED_DATAPATHS = 6  # 4 APs + 2 switches


def _load(name: str) -> Any:
    return json.loads((FIXTURES / f"ryu_{name}.json").read_text())


PORTS = _load("ports")["ports"]
FLOWS = _load("flows")["flows"]
TOPOLOGY = _load("topology")


@pytest.mark.parametrize("record", PORTS, ids=lambda r: f"{r['dpid']}:{r['port']}")
def test_port_records_validate_as_port_stats(record: dict[str, Any]) -> None:
    PortStats.model_validate({**record, **META})


@pytest.mark.parametrize("record", FLOWS, ids=lambda r: r["flow_id"][:40])
def test_flow_records_validate_as_flow_stats(record: dict[str, Any]) -> None:
    FlowStats.model_validate({**{k: record[k] for k in FLOW_FIELDS}, **META})


def test_flow_records_carry_controller_extras() -> None:
    for record in FLOWS:
        assert {"ours", "priority", "match"} <= set(record)
        assert record["ours"] is False  # fixtures were taken before any API flow was installed


def test_every_datapath_reports_ports_and_flows() -> None:
    assert len({r["dpid"] for r in PORTS}) == EXPECTED_DATAPATHS
    assert len({r["dpid"] for r in FLOWS}) == EXPECTED_DATAPATHS


def test_topology_shape() -> None:
    assert len(TOPOLOGY["switches"]) == EXPECTED_DATAPATHS
    for switch in TOPOLOGY["switches"]:
        assert len(switch["dpid"]) == 16
        assert all({"port_no", "name", "hw_addr"} <= set(p) for p in switch["ports"])
    assert all({"mac", "dpid", "port"} <= set(h) for h in TOPOLOGY["hosts"])
