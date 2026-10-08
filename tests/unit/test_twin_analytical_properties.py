"""P3.3 analytical simulator: invariants over random campus states (hypothesis), and speed."""

from __future__ import annotations

import dataclasses
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from common.schemas import CHANNELS_24GHZ, QOS_QUEUE_IDS
from twin.radio import load_radio_params
from twin.sim.analytical import SimResult, load_sim_params, simulate
from twin.state.builder import load_campus_aps
from twin.state.model import APState, FlowState, StationState, TwinState

ROOT = Path(__file__).resolve().parents[2]
CAMPUS_RAW = yaml.safe_load((ROOT / "config" / "campus_v1.yaml").read_text())
CAMPUS = load_campus_aps(CAMPUS_RAW)
RADIO = load_radio_params(CAMPUS_RAW)
PARAMS = load_sim_params(yaml.safe_load((ROOT / "config" / "sim.yaml").read_text()))
TS = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
APS = sorted(CAMPUS.positions)
STATIONS = [f"sta{i}" for i in range(1, 21)]


@st.composite
def states(draw: st.DrawFn) -> TwinState:
    """The campus's 4 APs (any channel, up or down), 20 stations anywhere, 0-3 flows each."""
    aps = {
        name: APState(
            name,
            CAMPUS.positions[name],
            draw(st.sampled_from(CHANNELS_24GHZ)),
            draw(st.booleans()),
            util=0.0,
        )
        for name in APS
    }
    stations = {
        s: StationState(s, (0.0, 0.0), draw(st.sampled_from([*APS, None]))) for s in STATIONS
    }
    flows = {}
    for s in STATIONS:
        for app in draw(st.sets(st.sampled_from(["video", "web", "bulk"]), max_size=3)):
            limit = draw(st.none() | st.floats(min_value=1.0, max_value=10.0))
            queue = draw(st.sampled_from(QOS_QUEUE_IDS))
            fid = f"{s}-{app}"
            flows[fid] = FlowState(
                fid, s, app, 0.0, 0.0, 0.0, queue_id=queue, rate_limit_mbps=limit
            )
    return TwinState(TS, aps, stations, flows)


def _non_web_rate(result: SimResult, state: TwinState, ap: str) -> float:
    return sum(
        result.flows[f.flow_id].throughput_mbps
        for f in state.flows.values()
        if f.app_class != "web" and state.stations[f.sta].ap == ap
    )


@settings(max_examples=200, deadline=None)
@given(states())
def test_predictions_stay_physical(state: TwinState) -> None:
    result = simulate(state, RADIO, PARAMS)
    assert set(result.flows) == set(state.flows)
    for ap in state.up_aps():  # an AP never carries more than its full capacity
        assert _non_web_rate(result, state, ap.name) <= RADIO.ap_capacity_mbps + 1e-9
        assert 0.0 <= result.ap_util[ap.name] <= 1.0
    offered = {"video": PARAMS.video_mbps, "bulk": PARAMS.bulk_mbps}
    for flow in state.flows.values():
        r = result.flows[flow.flow_id]
        assert 0.0 <= r.loss_pct <= 100.0
        assert r.latency_ms >= PARAMS.base_latency_ms
        if flow.rate_limit_mbps is not None:
            assert r.throughput_mbps <= flow.rate_limit_mbps + 1e-9
        if flow.app_class in offered:
            assert r.throughput_mbps <= offered[flow.app_class] + 1e-9
    assert 0.0 < result.kpis.jain <= 1.0 + 1e-9


@settings(max_examples=200, deadline=None)
@given(states(), st.data())
def test_a_higher_priority_queue_never_hurts_a_flow(state: TwinState, data: st.DataObject) -> None:
    if not state.flows:
        return
    fid = data.draw(st.sampled_from(sorted(state.flows)))
    flow = state.flows[fid]
    order = [2, 0, 1]  # background < best effort < priority
    if flow.queue_id == 1:
        return
    better = order[order.index(flow.queue_id) + 1]
    raised = dataclasses.replace(
        state, flows={**state.flows, fid: dataclasses.replace(flow, queue_id=better)}
    )
    before = simulate(state, RADIO, PARAMS).flows[fid]
    after = simulate(raised, RADIO, PARAMS).flows[fid]
    assert after.throughput_mbps >= before.throughput_mbps - 1e-9
    assert after.latency_ms <= before.latency_ms + 1e-9


@settings(max_examples=100, deadline=None)
@given(states())
def test_more_capacity_never_lowers_a_flow(state: TwinState) -> None:
    bigger = dataclasses.replace(RADIO, ap_capacity_mbps=RADIO.ap_capacity_mbps * 2)
    before = simulate(state, RADIO, PARAMS)
    after = simulate(state, bigger, PARAMS)
    for fid in state.flows:
        assert after.flows[fid].throughput_mbps >= before.flows[fid].throughput_mbps - 1e-9


@settings(max_examples=50, deadline=None)
@given(states())
def test_the_result_does_not_depend_on_dict_order(state: TwinState) -> None:
    reordered = TwinState(
        state.ts,
        dict(reversed(list(state.aps.items()))),
        dict(reversed(list(state.stations.items()))),
        dict(reversed(list(state.flows.items()))),
    )
    assert simulate(state, RADIO, PARAMS) == simulate(reordered, RADIO, PARAMS)


def test_a_full_campus_simulates_well_under_a_second() -> None:
    aps = {n: APState(n, CAMPUS.positions[n], 1, True, 0.0) for n in APS}
    stations = {s: StationState(s, (0.0, 0.0), APS[i % 4]) for i, s in enumerate(STATIONS)}
    flows = {
        f"{s}-{a}": FlowState(f"{s}-{a}", s, a, 0.0, 0.0, 0.0)
        for s in STATIONS
        for a in ("video", "web", "bulk")
    }
    state = TwinState(TS, aps, stations, flows)
    start = time.perf_counter()
    for _ in range(100):
        simulate(state, RADIO, PARAMS)
    per_run = (time.perf_counter() - start) / 100
    assert per_run < 1.0  # PHASE_PLAN P3.3 Done when
    print(f"P3.3 simulate: {per_run * 1000:.2f} ms per run (60 flows)")
