"""P3.3 analytical simulator (twin/sim/analytical.py): worked examples.

Expected values are worked out by hand from the model in the module docstring (config/sim.yaml
numbers), not by calling the simulator.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from twin.radio import RadioParams
from twin.sim.analytical import AppModel, SimParams, load_sim_params, simulate
from twin.state.model import APState, FlowState, StationState, TwinState

ROOT = Path(__file__).resolve().parents[2]
PARAMS = load_sim_params(yaml.safe_load((ROOT / "config" / "sim.yaml").read_text()))
RADIO = RadioParams(
    ap_capacity_mbps=4.6,
    cochannel_full_m=30.0,
    cochannel_zero_m=60.0,
    rssi_at_1m_dbm=-16.0,
    path_loss_exp=4.0,
)
TS = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)


def _state(aps: list[APState], clients: dict[str, str | None], flows: list[FlowState]) -> TwinState:
    stations = {s: StationState(s, (0.0, 0.0), ap) for s, ap in clients.items()}
    return TwinState(TS, {a.name: a for a in aps}, stations, {f.flow_id: f for f in flows})


def _ap(name: str, x: float = 0.0, channel: int = 1, up: bool = True) -> APState:
    return APState(name, (x, 0.0), channel, up, util=0.0)


def _flow(sta: str, app: str = "video", queue: int = 0, limit: float | None = None) -> FlowState:
    return FlowState(f"{sta}-{app}", sta, app, 0.0, 0.0, 0.0, queue_id=queue, rate_limit_mbps=limit)


def _videos(n: int, ap: str = "ap1") -> tuple[dict[str, str | None], list[FlowState]]:
    clients: dict[str, str | None] = {f"sta{i}": ap for i in range(1, n + 1)}
    return clients, [_flow(s) for s in clients]


def test_params_come_from_the_config() -> None:
    assert PARAMS.apps["video"] == AppModel(offered_mbps=1.0, elastic=False, fetch=False)
    assert PARAMS.apps["bulk"].elastic
    assert PARAMS.apps["web"].fetch
    assert PARAMS.queue_slots == 6
    assert PARAMS.dead_latency_ms == 1000.0


def test_the_simulator_is_off_until_its_exit_gate_passes() -> None:
    assert PARAMS.enabled is False  # RULEBOOK B-5


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load((ROOT / "config" / "sim.yaml").read_text())
    return raw


def _bad_app(**entry: Any) -> dict[str, Any]:
    apps = _raw()["apps"]
    return {"apps": {**apps, "video": {**apps["video"], **entry}}}


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"queue_slots": 0}, "queue_slots"),
        ({"fetch_efficiency": 1.5}, "fetch_efficiency"),
        ({"base_latency_ms": -1}, "base_latency_ms"),
        ({"enabled": "yes"}, "enabled"),
        ({"extra": 1}, "extra"),
        ({"apps": {"video": {"offered_mbps": 1.0, "elastic": False, "fetch": False}}}, "apps"),
        (_bad_app(offered_mbps=-1), "apps.video.offered_mbps"),
        (_bad_app(elastic="no"), "apps.video.elastic"),
        (_bad_app(colour="red"), "apps.video"),
    ],
)
def test_bad_params_are_rejected_by_name(change: dict[str, Any], named: str) -> None:
    with pytest.raises(ValueError, match=named):
        load_sim_params(_raw() | change)


def _with_bulk(offered_mbps: float) -> SimParams:
    bulk = AppModel(offered_mbps, elastic=True, fetch=False)
    return dataclasses.replace(PARAMS, apps={**PARAMS.apps, "bulk": bulk})


def test_below_capacity_every_flow_gets_its_demand() -> None:
    clients, flows = _videos(2)
    result = simulate(_state([_ap("ap1")], clients, flows), RADIO, PARAMS)
    for f in flows:
        assert result.flows[f.flow_id].throughput_mbps == pytest.approx(1.0)
        assert result.flows[f.flow_id].loss_pct == pytest.approx(0.2)
        # rho = 2 / 4.6 = 0.4348: M/M/1/K (K=6) mean queue 0.7486 -> 0.8 + 2.5 * 0.7486 ms
        assert result.flows[f.flow_id].latency_ms == pytest.approx(2.6715, abs=1e-4)
    assert result.ap_util["ap1"] == pytest.approx(2 / 4.6)


def test_above_capacity_flows_share_it_and_inelastic_traffic_loses_the_rest() -> None:
    clients, flows = _videos(6)
    result = simulate(_state([_ap("ap1")], clients, flows), RADIO, PARAMS)
    for f in flows:
        assert result.flows[f.flow_id].throughput_mbps == pytest.approx(4.6 / 6)
        assert result.flows[f.flow_id].loss_pct == pytest.approx(23.5333, abs=1e-4)
        # rho = 6 / 4.6 = 1.3043: the bounded queue holds 4.005 packets on average
        assert result.flows[f.flow_id].latency_ms == pytest.approx(10.8126, abs=1e-4)
    assert result.ap_util["ap1"] == pytest.approx(1.0)


def test_a_flow_without_a_working_ap_is_dead() -> None:
    aps = [_ap("ap1"), _ap("ap2", x=100.0, up=False)]
    clients: dict[str, str | None] = {"sta1": None, "sta2": "ap2"}
    result = simulate(_state(aps, clients, [_flow("sta1"), _flow("sta2")]), RADIO, PARAMS)
    for flow_id in ("sta1-video", "sta2-video"):
        dead = result.flows[flow_id]
        assert (dead.throughput_mbps, dead.loss_pct, dead.latency_ms) == (0.0, 100.0, 1000.0)
    assert "ap2" not in result.ap_util  # only APs that are up have a utilisation


def test_a_higher_priority_queue_is_served_first() -> None:
    clients, flows = _videos(6)
    flows = [_flow(f.sta, queue=1) if f.sta in ("sta1", "sta2") else f for f in flows]
    result = simulate(_state([_ap("ap1")], clients, flows), RADIO, PARAMS)
    for sta in ("sta1", "sta2"):  # queue 1: 2 Mbit/s, served in full, sees only its own load
        assert result.flows[f"{sta}-video"].throughput_mbps == pytest.approx(1.0)
        assert result.flows[f"{sta}-video"].latency_ms == pytest.approx(2.6715, abs=1e-4)
    for sta in ("sta3", "sta4", "sta5", "sta6"):  # queue 0 shares the 2.6 Mbit/s left
        assert result.flows[f"{sta}-video"].throughput_mbps == pytest.approx(0.65)
        assert result.flows[f"{sta}-video"].loss_pct == pytest.approx(35.2)
        assert result.flows[f"{sta}-video"].latency_ms == pytest.approx(10.8126, abs=1e-4)


def test_background_queue_gets_only_what_best_effort_leaves() -> None:
    clients, flows = _videos(6)
    flows = [_flow(f.sta, queue=2) if f.sta == "sta6" else f for f in flows]
    result = simulate(_state([_ap("ap1")], clients, flows), RADIO, PARAMS)
    # best effort: 5 videos want 5 Mbit/s > 4.6, so they share it all and nothing is left
    assert result.flows["sta1-video"].throughput_mbps == pytest.approx(4.6 / 5)
    assert result.flows["sta6-video"].throughput_mbps == pytest.approx(0.0, abs=1e-9)


def test_a_same_channel_neighbour_caps_capacity() -> None:
    # 40 m apart on channel 1: load (60 - 40) / 30 = 0.667 -> 4.6 / 1.667 = 2.76 Mbit/s each
    aps = [_ap("ap1", x=0.0), _ap("ap2", x=40.0)]
    clients, flows = _videos(4)
    result = simulate(_state(aps, clients, flows), RADIO, PARAMS)
    assert result.flows["sta1-video"].throughput_mbps == pytest.approx(2.76 / 4)
    assert result.ap_util["ap1"] == pytest.approx(1.0)
    moved = [_ap("ap1", x=0.0), _ap("ap2", x=40.0, channel=6)]
    assert simulate(_state(moved, clients, flows), RADIO, PARAMS).flows[
        "sta1-video"
    ].throughput_mbps == pytest.approx(1.0)


def test_a_web_fetch_gets_a_share_of_the_capacity_left_over() -> None:
    # 2 video flows use 2 Mbit/s: a fetch runs at 0.8 * (4.6 - 2) = 2.08 Mbit/s (KPI probe metric)
    clients, flows = _videos(2)
    clients["sta3"] = "ap1"
    result = simulate(_state([_ap("ap1")], clients, [*flows, _flow("sta3", "web")]), RADIO, PARAMS)
    assert result.flows["sta3-web"].throughput_mbps == pytest.approx(2.08)
    assert result.flows["sta3-web"].loss_pct == pytest.approx(0.2)


def test_a_rate_limit_only_binds_below_the_demand() -> None:
    params = _with_bulk(3.0)
    clients: dict[str, str | None] = {"sta1": "ap1", "sta2": "ap1"}
    flows = [_flow("sta1", "bulk", limit=1.0), _flow("sta2", "bulk", limit=5.0)]
    result = simulate(_state([_ap("ap1")], clients, flows), RADIO, params)
    assert result.flows["sta1-bulk"].throughput_mbps == pytest.approx(1.0)
    assert result.flows["sta2-bulk"].throughput_mbps == pytest.approx(3.0)  # 4.6 - 1 >= 3
    assert result.flows["sta1-bulk"].loss_pct == pytest.approx(0.2)  # TCP adapts to the limit


def test_network_kpis_sum_throughput_and_average_latency_and_loss() -> None:
    aps = [_ap("ap1"), _ap("ap2", x=100.0, channel=6)]
    clients: dict[str, str | None] = {"sta1": "ap1", "sta2": "ap1", "sta3": "ap1", "sta4": "ap2"}
    flows = [_flow("sta1"), _flow("sta4")]
    kpis = simulate(_state(aps, clients, flows), RADIO, PARAMS).kpis
    # one video per AP, each alone: rho = 1 / 4.6 = 0.2174 -> queue 0.2776 -> 1.4940 ms
    assert kpis.throughput_mbps == pytest.approx(2.0)
    assert kpis.latency_ms == pytest.approx(1.4940, abs=1e-4)
    assert kpis.loss_pct == pytest.approx(0.2)
    assert kpis.jain == pytest.approx(0.8)  # clients 3 and 1: 16 / (2 * 10)


def test_no_flows_and_no_clients_is_a_quiet_fair_network() -> None:
    kpis = simulate(_state([_ap("ap1")], {}, []), RADIO, PARAMS).kpis
    assert (kpis.throughput_mbps, kpis.latency_ms, kpis.loss_pct, kpis.jain) == (0.0, 0.0, 0.0, 1.0)


def test_a_queue_at_exactly_full_load_holds_half_its_slots() -> None:
    # rho = 1: the M/M/1/K formula is 0/0 there; its limit is K/2 = 3 -> 0.8 + 2.5 * 3 ms
    params = _with_bulk(4.6)
    clients: dict[str, str | None] = {"sta1": "ap1"}
    result = simulate(_state([_ap("ap1")], clients, [_flow("sta1", "bulk")]), RADIO, params)
    assert result.flows["sta1-bulk"].latency_ms == pytest.approx(8.3)


def test_network_throughput_counts_traffic_on_the_air_not_fetch_rates() -> None:
    # 10 web stations: each fetch runs at 0.8 * 4.6 = 3.68 Mbit/s (what the probe reports), but
    # fetches rarely overlap: the AP carries 10 * 0.08 = 0.8 Mbit/s, and that is what adds up
    clients: dict[str, str | None] = {f"sta{i}": "ap1" for i in range(10)}
    flows = [_flow(s, "web") for s in clients]
    result = simulate(_state([_ap("ap1")], clients, flows), RADIO, PARAMS)
    assert result.flows["sta0-web"].throughput_mbps == pytest.approx(3.68)
    assert result.kpis.throughput_mbps == pytest.approx(0.8)


def test_a_stations_flows_all_get_the_latency_of_its_ping_queue() -> None:
    # the probe pings once per station and its replies follow the station's highest-priority
    # flow (decision P4.4a-A): sta1's bulk flow, in queue 0, reports queue 1's latency
    clients, flows = _videos(6)
    flows = [_flow("sta1", queue=1), *flows[1:], _flow("sta1", "bulk")]
    result = simulate(_state([_ap("ap1")], clients, flows), RADIO, PARAMS)
    # queue 1 holds 1 Mbit/s: rho 1/4.6 -> 1.4940 ms (see the network KPI test)
    assert result.flows["sta1-video"].latency_ms == pytest.approx(1.4940, abs=1e-4)
    assert result.flows["sta1-bulk"].latency_ms == pytest.approx(1.4940, abs=1e-4)
    assert result.flows["sta2-video"].latency_ms > 10  # best effort is saturated
