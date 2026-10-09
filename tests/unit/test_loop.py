"""P4.5 control loop (api/loop.py): V1 / V2 / V3 behaviour per tick."""

from __future__ import annotations

import dataclasses
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from api import loop as api_loop
from api.loop import COOLDOWN_S, Loop, load_loop_config
from common.schemas import Action, KPIValues
from controller.executor.executor import Executor, load_executor_config
from controller.executor.ledger import Ledger
from ml.optimizer.heuristics import load_heuristic_config
from twin.radio import RadioParams
from twin.sim.analytical import load_sim_params
from twin.state.builder import CampusAPs
from twin.state.model import APState, FlowState, StationState, TwinState
from twin.verify.verifier import VerifyContext, load_verify_config, verify

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
RADIO = RadioParams(4.6, 30.0, 60.0, -16.0, 4.0)
CAMPUS = CampusAPs({"ap1": (0.0, 0.0), "ap2": (20.0, 0.0)}, {"ap1": 1, "ap2": 6}, {})
GOOD = KPIValues(throughput_mbps=1.0, latency_ms=10.0, loss_pct=1.0, jain=0.8)


def _yaml(name: str) -> Any:
    return yaml.safe_load((ROOT / "config" / name).read_text())


def _crowded(util: float = 0.95) -> TwinState:
    """ap1 congested with 6 video clients, ap2 nearby and idle: the heuristics steer one."""
    clients = {f"sta{i}": StationState(f"sta{i}", (5.0, 0.0), "ap1") for i in range(1, 7)}
    flows = {
        f"sta{i}-video": FlowState(f"sta{i}-video", f"sta{i}", "video", 0, 0, 0)
        for i in range(1, 7)
    }
    aps = {
        "ap1": APState("ap1", (0.0, 0.0), 1, True, util, 14.0),
        "ap2": APState("ap2", (20.0, 0.0), 6, True, 0.1, 14.0),
    }
    return TwinState(T0, aps, clients, flows)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class FakeActuator:
    def __init__(self) -> None:
        self.applied: list[str] = []

    def apply(self, action: Action, state: TwinState) -> dict[str, Any]:
        self.applied.append(action.type)
        return {}

    def revert(self, action: Action, previous: dict[str, Any]) -> None:
        return None


class SteadyKpis:
    def window(self, start: datetime, end: datetime) -> KPIValues:
        return GOOD


def _loop(
    tmp_path: Path, mode: str, medium_needs_approval: bool = True, state: TwinState | None = None
) -> tuple[Loop, FakeActuator, Clock]:
    clock, actuator = Clock(), FakeActuator()
    loop_config = load_loop_config({"mode": mode, "period_s": 5, "evaluation": mode == "V2"})
    executor_config = load_executor_config(_yaml("executor.yaml"))
    if loop_config.mode == "V2":
        executor_config = dataclasses.replace(executor_config, unverified_ok=True)  # ADR-005
    executor = Executor(Ledger(tmp_path / "l.db"), actuator, SteadyKpis(), executor_config, clock)
    verify_config = dataclasses.replace(
        load_verify_config(_yaml("verify.yaml")),
        medium_auto_apply=frozenset() if medium_needs_approval else frozenset({"steer_clients"}),
    )
    context = VerifyContext(CAMPUS, RADIO, load_sim_params(_yaml("sim.yaml")), verify_config)
    current = state or _crowded()
    loop = Loop(
        loop_config,
        lambda: dataclasses.replace(current, ts=clock()),  # each refresh is a newer state
        executor,
        context,
        load_heuristic_config(_yaml("optimizer.yaml")),
    )
    return loop, actuator, clock


def test_v1_never_acts(tmp_path: Path) -> None:
    loop, actuator, _ = _loop(tmp_path, "V1")
    assert loop.tick() == []
    assert actuator.applied == []


def test_v3_applies_an_accepted_action_that_needs_no_approval(tmp_path: Path) -> None:
    loop, actuator, _ = _loop(tmp_path, "V3", medium_needs_approval=False)
    [(_, outcome)] = loop.tick()
    assert outcome == "applied"
    assert actuator.applied == ["steer_clients"]


def test_v3_leaves_an_action_that_needs_approval_to_the_operator(tmp_path: Path) -> None:
    loop, actuator, clock = _loop(tmp_path, "V3")  # medium needs approval until P3.5
    [(_, outcome)] = loop.tick()
    assert outcome == "awaiting approval"
    assert actuator.applied == []
    clock.now += timedelta(seconds=5)
    assert loop.tick() == []  # the same proposal is not recorded again every tick


def test_v3_proposes_nothing_while_an_action_is_watched(tmp_path: Path) -> None:
    loop, actuator, clock = _loop(tmp_path, "V3", medium_needs_approval=False)
    loop.tick()
    clock.now += timedelta(seconds=5)
    assert loop.tick() == []  # one change at a time: the steer is still under its 30 s watch
    clock.now += timedelta(seconds=30)
    events = loop.tick()  # the watch ends (kept), then the loop may act again
    assert "kept" in [o for _, o in events]
    assert actuator.applied.count("steer_clients") == 2


def test_v3_does_not_steer_clients_out_of_range(tmp_path: Path) -> None:
    # every client sits 95 m from ap2: a steer would leave it at -95 dBm (ADR-004 bound)
    far = _crowded()
    stations = {s: dataclasses.replace(st, position=(-75.0, 0.0)) for s, st in far.stations.items()}
    loop, actuator, _ = _loop(tmp_path, "V3", state=dataclasses.replace(far, stations=stations))
    assert loop.tick() == []  # the heuristics' own RSSI check finds no movable client
    assert actuator.applied == []


def test_v2_applies_without_waiting_for_approval(tmp_path: Path) -> None:
    loop, actuator, _ = _loop(tmp_path, "V2")  # medium would need approval in V3
    [(_, outcome)] = loop.tick()
    assert outcome == "applied"
    assert actuator.applied == ["steer_clients"]


def test_a_quiet_network_gets_no_proposals(tmp_path: Path) -> None:
    loop, _, _ = _loop(tmp_path, "V3", state=_crowded(util=0.3))
    assert loop.tick() == []


@pytest.mark.parametrize(
    ("raw", "named"),
    [
        ({"mode": "V2", "period_s": 5, "evaluation": False}, "evaluation"),
        ({"mode": "V4", "period_s": 5, "evaluation": False}, "mode"),
        ({"mode": "V3", "period_s": 0, "evaluation": False}, "period_s"),
        ({"mode": "V3", "period_s": 5, "evaluation": "no"}, "evaluation"),
        ({"mode": "V3", "period_s": 5, "evaluation": False, "x": 1}, "unknown"),
    ],
)
def test_bad_loop_configs_are_refused(raw: dict[str, Any], named: str) -> None:
    with pytest.raises(ValueError, match=named):
        load_loop_config(raw)


def test_the_shipped_loop_config_is_v3_and_not_an_evaluation() -> None:
    config = load_loop_config(_yaml("loop.yaml"))
    assert (config.mode, config.period_s, config.evaluation) == ("V3", 5.0, False)


def test_a_stalled_state_is_not_handled_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop, actuator, clock = _loop(tmp_path, "V3", medium_needs_approval=False)
    stalled = _crowded()
    monkeypatch.setattr(loop, "_state", lambda: stalled)  # telemetry stopped: same state
    loop.tick()
    clock.now += timedelta(seconds=30)
    events = loop.tick()  # the watch ends; the same proposal (same id) is not handled again
    assert [o for _, o in events] == ["kept"]
    assert actuator.applied == ["steer_clients"]


def test_v3_applies_nothing_the_twin_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop, actuator, _ = _loop(tmp_path, "V3", medium_needs_approval=False)

    def rejecting(state: TwinState, actions: Any, context: VerifyContext) -> Any:
        return [
            v.model_copy(update={"accepted": False, "violations": ["latency_ms 9% worse"]})
            for v in verify(state, actions, context)
        ]

    monkeypatch.setattr(api_loop, "verify", rejecting)
    [(_, outcome)] = loop.tick()
    assert outcome == "rejected"
    assert actuator.applied == []


def test_a_rate_limited_apply_is_reported_and_retried_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop, actuator, _ = _loop(tmp_path, "V3", medium_needs_approval=False)
    tight = dataclasses.replace(loop._executor._config, max_actions_per_loop=1)
    monkeypatch.setattr(loop._executor, "_config", tight)
    # one action already applied in this loop period
    monkeypatch.setattr(loop._executor._ledger, "applied_since", lambda since: ["earlier"])
    [(_, outcome)] = loop.tick()
    assert outcome.startswith("not applied: at most 1 actions")
    assert actuator.applied == []


def test_run_ticks_until_stopped_and_survives_a_failing_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop, _, _ = _loop(tmp_path, "V3")
    calls: list[int] = []
    stop = threading.Event()

    def tick() -> list[tuple[str, str]]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("influx unreachable")  # logged, the loop goes on
        stop.set()
        return [("act_x", "applied")]

    monkeypatch.setattr(loop, "tick", tick)
    monkeypatch.setattr(loop, "_config", dataclasses.replace(loop._config, period_s=0.001))
    loop.run(stop)
    assert len(calls) == 2


class WorseKpis:
    """Live KPIs that always look worse after an action: every watch rolls back."""

    def window(self, start: datetime, end: datetime) -> KPIValues:
        return GOOD if end <= T0 else GOOD.model_copy(update={"loss_pct": 9.0})


def test_a_rolled_back_proposal_is_not_retried_during_the_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop, actuator, clock = _loop(tmp_path, "V3", medium_needs_approval=False)
    monkeypatch.setattr(loop._executor, "_kpis", WorseKpis())
    loop.tick()  # the steer is applied ...
    clock.now += timedelta(seconds=30)
    events = loop.tick()  # ... rolled back after its watch, and the same steer not tried again
    assert [o for _, o in events] == ["rolled_back"]
    clock.now += timedelta(seconds=COOLDOWN_S - 1)  # the cooldown counts from the rollback
    assert loop.tick() == []  # still cooling down
    clock.now += timedelta(seconds=2)
    assert [o for _, o in loop.tick()] == ["applied"]  # cooldown over: it may be tried again
    assert actuator.applied == ["steer_clients", "steer_clients"]


def test_a_rollback_seen_while_another_action_is_watched_still_cools_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # found live (V3, seed 43): a steer rolled back while a second steer was still being
    # watched; that tick returned early and the first steer was re-applied 47 s later
    loop, actuator, clock = _loop(tmp_path, "V3", medium_needs_approval=False)
    [(first_id, _)] = loop.tick()  # the steer is applied
    signature = loop._applied[first_id]
    executor = loop._executor
    monkeypatch.setattr(executor, "check", lambda: [(first_id, "rolled_back")])
    monkeypatch.setattr(executor, "history", lambda status=None: ["another action, watched"])
    clock.now += timedelta(seconds=30)
    loop.tick()  # sees the rollback, then returns early: something else is still watched
    monkeypatch.setattr(executor, "check", lambda: [])
    monkeypatch.setattr(executor, "history", lambda status=None: [])
    clock.now += timedelta(seconds=45)
    assert loop.tick() == []  # 75 s after the rollback: still cooling down, not re-applied
    assert signature in loop._cooling
    assert actuator.applied == ["steer_clients"]
