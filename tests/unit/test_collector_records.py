"""P2.1 collector: VM responses -> schema records (telemetry/collector/records.py).

Uses the real responses recorded on the VM (tests/fixtures/ryu, ap_agent, traffic).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from common.schemas import APStats, FlowStats, KPIRecord, PortStats, StationStats
from telemetry.collector.records import (
    Meta,
    from_ap_stats,
    from_kpis,
    from_ryu_flows,
    from_ryu_ports,
    from_stations,
    line_protocol,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
META = Meta(scenario_id="lecture_flash_crowd", run_id="run-1")


def _load(path: str) -> Any:
    return json.loads((FIXTURES / path).read_text())


# ------------------------------------------------------------------ mapping
def test_ryu_ports_map_to_port_stats() -> None:
    body = _load("ryu/ryu_ports.json")
    batch = from_ryu_ports(body, META)
    assert len(batch.records) == len(body["ports"])
    assert not batch.errors
    assert all(isinstance(r, PortStats) and r.run_id == "run-1" for r in batch.records)


def test_ryu_flows_drop_controller_extras() -> None:
    body = _load("ryu/ryu_flows.json")
    batch = from_ryu_flows(body, META)
    assert len(batch.records) == len(body["flows"])
    assert all(isinstance(r, FlowStats) for r in batch.records)


def test_ap_stats_record_maps() -> None:
    record = _load("ap_agent/ap_agent_ap_stats.json")["aps"][0]
    batch = from_ap_stats(record, META)
    assert [type(r) for r in batch.records] == [APStats]


def test_stations_take_the_response_timestamp() -> None:
    body = _load("ap_agent/ap_agent_stations.json")
    batch = from_stations(body, META)
    assert len(batch.records) == len(body["stations"])
    assert all(isinstance(r, StationStats) for r in batch.records)
    assert batch.records[0].ts == datetime.fromisoformat(body["ts"])


def test_kpis_map() -> None:
    body = _load("traffic/kpi_response.json")
    batch = from_kpis(body, META)
    assert len(batch.records) == len(body["kpis"])
    assert all(isinstance(r, KPIRecord) for r in batch.records)


def test_invalid_records_are_dropped_with_a_reason() -> None:
    body = _load("traffic/kpi_response.json")
    bad = {**body["kpis"][0], "loss_pct": 140.0}
    batch = from_kpis({"ts": body["ts"], "kpis": [bad, body["kpis"][1]]}, META)
    assert len(batch.records) == 1
    assert len(batch.errors) == 1
    assert "loss_pct" in batch.errors[0]


def test_non_object_items_are_dropped_with_a_reason() -> None:
    batch = from_kpis({"kpis": [5]}, META)
    assert batch.records == []
    assert batch.errors == ["KPIRecord: TypeError: 'int' object is not iterable"]


@pytest.mark.parametrize(
    ("mapper", "body"),
    [
        (from_ryu_ports, {"oops": []}),
        (from_ryu_flows, []),
        (from_stations, {"stations": "none"}),
        (from_kpis, None),
    ],
)
def test_malformed_responses_are_errors_not_crashes(mapper: Any, body: Any) -> None:
    batch = mapper(body, META)
    assert batch.records == []
    assert len(batch.errors) == 1


# ------------------------------------------------------------------ line protocol
TS = datetime(2026, 10, 8, 10, 0, 1, 500000, tzinfo=UTC)
NS = 1_791_453_601_500_000_000


def test_kpi_line_has_tags_fields_and_ns_timestamp() -> None:
    record = KPIRecord(
        ts=TS,
        scenario_id="lecture_flash_crowd",
        run_id="run-1",
        flow_id="sta5-video",
        app_class="video",
        throughput_mbps=0.4,
        latency_ms=12.5,
        jitter_ms=1.0,
        loss_pct=0.0,
    )
    assert line_protocol(record) == (
        "kpi,app_class=video,flow_id=sta5-video,run_id=run-1,scenario_id=lecture_flash_crowd "
        f"jitter_ms=1.0,latency_ms=12.5,loss_pct=0.0,throughput_mbps=0.4 {NS}"
    )


def test_integers_get_the_i_suffix_and_tags_are_strings() -> None:
    record = APStats(
        ts=TS,
        scenario_id="s",
        run_id="r",
        ap="ap1",
        channel=6,
        n_clients=3,
        channel_util=0.5,
        tx_power_dbm=14.0,
        retries=2.0,
        noise_dbm=-92.0,
    )
    assert line_protocol(record) == (
        "ap_stats,ap=ap1,channel=6,run_id=r,scenario_id=s "
        f"channel_util=0.5,n_clients=3i,noise_dbm=-92.0,retries=2.0,tx_power_dbm=14.0 {NS}"
    )


def test_missing_optional_fields_and_tags_are_left_out() -> None:
    record = StationStats(ts=TS, scenario_id="s", run_id="r", sta="sta3", ap=None, x=1.0, y=2.5)
    assert line_protocol(record) == f"sta_stats,run_id=r,scenario_id=s,sta=sta3 x=1.0,y=2.5 {NS}"


def test_tag_values_are_escaped() -> None:
    record = FlowStats(
        ts=TS,
        scenario_id="s",
        run_id="r",
        dpid="1",
        flow_id="a:b-c.d",
        bytes=10,
        pkts=1,
        duration_s=1.5,
        bps=0.0,
    )
    assert line_protocol(record).startswith("flow_stats,dpid=1,flow_id=a:b-c.d,run_id=r,")


def test_spaces_commas_and_equals_in_tags_are_escaped() -> None:
    record = PortStats.model_construct(  # bypass Identifier validation to test escaping only
        ts=TS,
        scenario_id="a b,c=d",
        run_id="r",
        dpid="1",
        port=1,
        rx_bytes=0,
        tx_bytes=0,
        rx_pkts=0,
        tx_pkts=0,
        rx_dropped=0,
        tx_dropped=0,
        rx_bps=0.0,
        tx_bps=0.0,
    )
    assert r"scenario_id=a\ b\,c\=d" in line_protocol(record)
