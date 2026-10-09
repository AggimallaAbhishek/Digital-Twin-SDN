"""P4.4 action executor (controller/executor/executor.py): the T-5 safety invariants.

(a) unverified actions are refused, (c) high-impact actions need approval, (d) rollback restores
the previous config; plus rate limits, all-or-nothing sets and the persistent audit ledger.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from common.schemas import ACTION_ADAPTER, Action, Impact, KPIValues, Verdict
from controller.executor.executor import Executor, ExecutorError, load_executor_config
from controller.executor.ledger import Ledger
from twin.state.model import TwinState

ROOT = Path(__file__).resolve().parents[2]
CONFIG = load_executor_config(yaml.safe_load((ROOT / "config" / "executor.yaml").read_text()))
T0 = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
STATE = TwinState(T0, {}, {})
GOOD = KPIValues(throughput_mbps=1.0, latency_ms=10.0, loss_pct=1.0, jain=0.8)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeActuator:
    """Records applies and reverts; can be told to fail on one action."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.applied: list[str] = []
        self.reverted: list[tuple[str, dict[str, Any]]] = []

    def apply(self, action: Action, state: TwinState) -> dict[str, Any]:
        if action.action_id == self.fail_on:
            raise RuntimeError("the radio did not apply the change")
        self.applied.append(action.action_id)
        return {"before": f"config of {action.action_id}"}

    def revert(self, action: Action, previous: dict[str, Any]) -> None:
        self.reverted.append((action.action_id, previous))


class FakeKpis:
    """Live KPIs: `before` for windows ending at or before the apply, `after` for later ones."""

    def __init__(self, before: KPIValues | None = GOOD, after: KPIValues | None = GOOD) -> None:
        self.before, self.after = before, after
        self.applied_at: datetime | None = None

    def window(self, start: datetime, end: datetime) -> KPIValues | None:
        if self.applied_at is None or end <= self.applied_at:
            return self.before
        return self.after


def _action(n: int, kind: str = "set_qos_queue", **params: Any) -> Action:
    defaults: dict[str, Any] = {
        "set_qos_queue": {"match": {"zone": "lab"}, "queue_id": 1},
        "set_ap_channel": {"ap": "ap1", "channel": 6},
        "steer_clients": {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta1"]},
    }
    return ACTION_ADAPTER.validate_python(
        {
            "action_id": f"act_t_{n}",
            "type": kind,
            "source": "operator",
            "reason": "test",
            "created_at": T0,
            "params": params or defaults[kind],
        }
    )


def _verdict(action: Action, accepted: bool = True, needs_approval: bool = False) -> Verdict:
    impact: dict[str, Impact] = {
        "set_qos_queue": "low",
        "steer_clients": "medium",
        "set_ap_channel": "high",
    }
    return Verdict(
        action_id=action.action_id,
        accepted=accepted,
        predicted=GOOD,
        baseline=GOOD,
        violations=[] if accepted else ["latency_ms 12.0% worse"],
        impact=impact[action.type],
        needs_approval=needs_approval or impact[action.type] == "high",
        sim_mode="analytical",
        sim_time_ms=1.0,
    )


def _executor(
    tmp_path: Path, actuator: FakeActuator | None = None, kpis: FakeKpis | None = None
) -> tuple[Executor, FakeActuator, FakeKpis, Clock]:
    clock, actuator, kpis = Clock(), actuator or FakeActuator(), kpis or FakeKpis()
    executor = Executor(Ledger(tmp_path / "actions.db"), actuator, kpis, CONFIG, clock)
    return executor, actuator, kpis, clock


def _apply(executor: Executor, kpis: FakeKpis, clock: Clock, ids: list[str]) -> None:
    kpis.applied_at = clock()
    executor.apply(ids, STATE)


# ---------------------------------------------------------------- T-5 (a): only verified actions


def test_an_action_without_a_verdict_is_refused(tmp_path: Path) -> None:
    executor, actuator, _, _ = _executor(tmp_path)
    with pytest.raises(ExecutorError, match="no verdict"):
        executor.apply(["act_t_1"], STATE)
    assert actuator.applied == []


def test_a_rejected_action_is_refused(tmp_path: Path) -> None:
    executor, actuator, _, _ = _executor(tmp_path)
    action = _action(1)
    executor.record([action], [_verdict(action, accepted=False)])
    with pytest.raises(ExecutorError, match="rejected"):
        executor.apply([action.action_id], STATE)
    assert actuator.applied == []
    assert executor.history()[0].status == "rejected"


def test_an_accepted_low_impact_action_applies_and_is_audited(tmp_path: Path) -> None:
    executor, actuator, kpis, clock = _executor(tmp_path)
    action = _action(1)
    executor.record([action], [_verdict(action)])
    _apply(executor, kpis, clock, [action.action_id])
    assert actuator.applied == ["act_t_1"]
    [record] = executor.history()
    assert record.status == "applied"
    assert record.previous == {"before": "config of act_t_1"}
    assert [e.status for e in executor.events("act_t_1")] == ["verified", "applied"]


def test_an_action_is_applied_only_once(tmp_path: Path) -> None:
    executor, _, kpis, clock = _executor(tmp_path)
    action = _action(1)
    executor.record([action], [_verdict(action)])
    _apply(executor, kpis, clock, [action.action_id])
    with pytest.raises(ExecutorError, match="already applied"):
        executor.apply([action.action_id], STATE)


# ---------------------------------------------------------------- T-5 (c): approval


def test_a_high_impact_action_waits_for_an_operator(tmp_path: Path) -> None:
    executor, actuator, kpis, clock = _executor(tmp_path)
    action = _action(1, "set_ap_channel")
    executor.record([action], [_verdict(action)])
    with pytest.raises(ExecutorError, match="approval"):
        executor.apply([action.action_id], STATE)
    assert actuator.applied == []
    executor.approve(action.action_id, by="abhishek")
    _apply(executor, kpis, clock, [action.action_id])
    assert actuator.applied == ["act_t_1"]
    assert executor.history()[0].approved_by == "abhishek"


def test_only_a_verified_action_that_needs_approval_can_be_approved(tmp_path: Path) -> None:
    executor, _, _, _ = _executor(tmp_path)
    low = _action(1)
    executor.record([low], [_verdict(low)])
    with pytest.raises(ExecutorError, match="does not need approval"):
        executor.approve(low.action_id, by="abhishek")
    with pytest.raises(ExecutorError, match="no verdict"):
        executor.approve("act_t_9", by="abhishek")
    rejected = _action(2, "set_ap_channel")
    executor.record([rejected], [_verdict(rejected, accepted=False)])
    with pytest.raises(ExecutorError, match="rejected"):
        executor.approve(rejected.action_id, by="abhishek")


# ---------------------------------------------------------------- T-5 (d): watch and rollback


def test_an_action_that_keeps_kpis_is_kept_after_the_watch(tmp_path: Path) -> None:
    executor, actuator, kpis, clock = _executor(tmp_path)
    action = _action(1)
    executor.record([action], [_verdict(action)])
    _apply(executor, kpis, clock, [action.action_id])
    clock.advance(29)
    assert executor.check() == []  # still watching
    clock.advance(1)
    assert executor.check() == [("act_t_1", "kept")]
    assert actuator.reverted == []


def test_a_regression_rolls_back_to_the_previous_config(tmp_path: Path) -> None:
    # +12 ms (+120%): past both the 10% rule and the 10.9 ms latency noise floor (P4.4-B)
    worse = GOOD.model_copy(update={"latency_ms": 22.0})
    executor, actuator, kpis, clock = _executor(tmp_path, kpis=FakeKpis(after=worse))
    action = _action(1)
    executor.record([action], [_verdict(action)])
    _apply(executor, kpis, clock, [action.action_id])
    clock.advance(30)
    assert executor.check() == [("act_t_1", "rolled_back")]
    assert actuator.reverted == [("act_t_1", {"before": "config of act_t_1"})]
    [record] = executor.history()
    assert "latency_ms" in record.note


@pytest.mark.parametrize(
    "after",
    [
        GOOD.model_copy(update={"loss_pct": 1.4}),  # +40%, but only 0.4 points: noise
        GOOD.model_copy(update={"latency_ms": 10.9}),  # +0.9 ms: under the 1 ms floor
        GOOD.model_copy(update={"throughput_mbps": 0.95}),  # -5%: under 10%
        GOOD.model_copy(update={"jain": 0.9, "latency_ms": 9.0}),  # better
    ],
)
def test_small_or_positive_changes_are_kept(tmp_path: Path, after: KPIValues) -> None:
    executor, _actuator, kpis, clock = _executor(tmp_path, kpis=FakeKpis(after=after))
    action = _action(1)
    executor.record([action], [_verdict(action)])
    _apply(executor, kpis, clock, [action.action_id])
    clock.advance(30)
    assert executor.check() == [("act_t_1", "kept")]


def test_no_live_kpis_to_judge_by_means_roll_back(tmp_path: Path) -> None:
    executor, _actuator, kpis, clock = _executor(tmp_path, kpis=FakeKpis(after=None))
    action = _action(1)
    executor.record([action], [_verdict(action)])
    _apply(executor, kpis, clock, [action.action_id])
    clock.advance(30)
    assert executor.check() == [("act_t_1", "rolled_back")]
    assert "no live KPIs" in executor.history()[0].note


def test_a_set_is_rolled_back_together_in_reverse_order(tmp_path: Path) -> None:
    worse = GOOD.model_copy(update={"loss_pct": 5.0})
    executor, actuator, kpis, clock = _executor(tmp_path, kpis=FakeKpis(after=worse))
    actions = [_action(1), _action(2, queue_id=2, match={"app_class": "bulk"})]
    executor.record(actions, [_verdict(a) for a in actions])
    _apply(executor, kpis, clock, [a.action_id for a in actions])
    clock.advance(30)
    assert sorted(executor.check()) == [("act_t_1", "rolled_back"), ("act_t_2", "rolled_back")]
    assert [a for a, _ in actuator.reverted] == ["act_t_2", "act_t_1"]


# ---------------------------------------------------------------- sets: all or nothing


def test_a_set_is_applied_whole_or_not_at_all(tmp_path: Path) -> None:
    executor, actuator, kpis, clock = _executor(tmp_path, actuator=FakeActuator(fail_on="act_t_2"))
    actions = [_action(1), _action(2, queue_id=2, match={"app_class": "bulk"})]
    executor.record(actions, [_verdict(a) for a in actions])
    with pytest.raises(ExecutorError, match="radio did not apply"):
        _apply(executor, kpis, clock, [a.action_id for a in actions])
    assert actuator.reverted == [("act_t_1", {"before": "config of act_t_1"})]
    assert {r.status for r in executor.history()} == {"failed"}


def test_part_of_a_verified_set_cannot_be_applied_alone(tmp_path: Path) -> None:
    executor, _, _, _ = _executor(tmp_path)
    actions = [_action(1), _action(2, queue_id=2, match={"app_class": "bulk"})]
    executor.record(actions, [_verdict(a) for a in actions])
    with pytest.raises(ExecutorError, match="whole set"):
        executor.apply(["act_t_1"], STATE)


def test_a_verdict_must_match_its_action(tmp_path: Path) -> None:
    executor, _, _, _ = _executor(tmp_path)
    with pytest.raises(ExecutorError, match="verdict"):
        executor.record([_action(1)], [_verdict(_action(2))])


# ---------------------------------------------------------------- rate limits (always on, N-6)


def test_one_high_impact_action_per_ap_per_two_minutes(tmp_path: Path) -> None:
    executor, actuator, kpis, clock = _executor(tmp_path)
    first, second = _action(1, "set_ap_channel"), _action(2, "set_ap_channel", ap="ap1", channel=11)
    for a in (first, second):
        executor.record([a], [_verdict(a)])
        executor.approve(a.action_id, by="abhishek")
    _apply(executor, kpis, clock, [first.action_id])
    clock.advance(60)
    with pytest.raises(ExecutorError, match="ap1"):
        executor.apply([second.action_id], STATE)
    clock.advance(60)
    _apply(executor, kpis, clock, [second.action_id])
    assert actuator.applied == ["act_t_1", "act_t_2"]


def test_at_most_n_actions_per_loop(tmp_path: Path) -> None:
    executor, _, kpis, clock = _executor(tmp_path)
    actions = [_action(n, queue_id=n % 3, match={"zone": "lab"}) for n in range(1, 5)]
    for a in actions:
        executor.record([a], [_verdict(a)])
    for a in actions[:3]:
        _apply(executor, kpis, clock, [a.action_id])
    with pytest.raises(ExecutorError, match="3 actions"):
        executor.apply([actions[3].action_id], STATE)
    clock.advance(5)
    _apply(executor, kpis, clock, [actions[3].action_id])


# ---------------------------------------------------------------- ledger and config


def test_the_ledger_survives_a_restart(tmp_path: Path) -> None:
    executor, _, kpis, clock = _executor(tmp_path)
    action = _action(1)
    executor.record([action], [_verdict(action)])
    _apply(executor, kpis, clock, [action.action_id])
    reopened = Ledger(tmp_path / "actions.db")
    assert [(r.action_id, r.status) for r in reopened.records()] == [("act_t_1", "applied")]
    assert executor.history(status="applied")[0].action_id == "act_t_1"
    assert executor.history(status="kept") == []


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"watch_s": 0}, "watch_s"),
        ({"regression_pct": 100}, "regression_pct"),
        ({"max_actions_per_loop": 0}, "max_actions_per_loop"),
        ({"high_impact_per_ap_s": 10}, "high_impact_per_ap_s"),
        ({"noise_floor": {"latency_ms": 1.0}}, "noise_floor"),
        (
            {"noise_floor": {"throughput_mbps": -1, "latency_ms": 1, "loss_pct": 1, "jain": 0}},
            "noise_floor",
        ),
        ({"rollback": False}, "unknown"),
    ],
)
def test_the_config_cannot_switch_the_safety_off(change: dict[str, Any], named: str) -> None:
    raw = yaml.safe_load((ROOT / "config" / "executor.yaml").read_text()) | change
    with pytest.raises(ValueError, match=named):
        load_executor_config(raw)


def test_an_approved_action_cannot_be_approved_again(tmp_path: Path) -> None:
    executor, _, _, _ = _executor(tmp_path)
    action = _action(1, "set_ap_channel")
    executor.record([action], [_verdict(action)])
    executor.approve(action.action_id, by="abhishek")
    with pytest.raises(ExecutorError, match="is approved"):
        executor.approve(action.action_id, by="someone else")


class BrokenRevert(FakeActuator):
    def revert(self, action: Action, previous: dict[str, Any]) -> None:
        raise RuntimeError("the agent is unreachable")


def test_a_rollback_that_fails_is_flagged_for_an_operator(tmp_path: Path) -> None:
    worse = GOOD.model_copy(update={"loss_pct": 5.0})
    executor, _, kpis, clock = _executor(tmp_path, BrokenRevert(), FakeKpis(after=worse))
    action = _action(1)
    executor.record([action], [_verdict(action)])
    _apply(executor, kpis, clock, [action.action_id])
    clock.advance(30)
    assert executor.check() == [("act_t_1", "rollback_failed")]
    assert "agent is unreachable" in executor.history()[0].note


def test_any_action_of_a_set_names_the_whole_set(tmp_path: Path) -> None:
    executor, _, _, _ = _executor(tmp_path)
    actions = [_action(1), _action(2, queue_id=2, match={"app_class": "bulk"})]
    executor.record(actions, [_verdict(a) for a in actions])
    assert executor.group_of("act_t_2") == ["act_t_1", "act_t_2"]
    with pytest.raises(ExecutorError, match="no verdict"):
        executor.group_of("act_t_9")


def test_an_action_id_is_recorded_once(tmp_path: Path) -> None:
    executor, _, _, _ = _executor(tmp_path)
    action = _action(1)
    executor.record([action], [_verdict(action)])
    with pytest.raises(ExecutorError, match="already recorded"):
        executor.record([action], [_verdict(action)])


# ---------------------------------------------------------------- V2 evaluation bypass (ADR-005)


def _v2_executor(
    tmp_path: Path, kpis: FakeKpis | None = None
) -> tuple[Executor, FakeActuator, FakeKpis, Clock]:
    clock, actuator, kpis = Clock(), FakeActuator(), kpis or FakeKpis()
    v2 = dataclasses.replace(CONFIG, unverified_ok=True)
    executor = Executor(Ledger(tmp_path / "v2.db"), actuator, kpis, v2, clock)
    return executor, actuator, kpis, clock


def test_v2_applies_what_the_twin_rejected_and_says_so(tmp_path: Path) -> None:
    executor, actuator, kpis, clock = _v2_executor(tmp_path)
    action = _action(1, "set_ap_channel")
    executor.record([action], [_verdict(action, accepted=False)])
    _apply(executor, kpis, clock, [action.action_id])  # rejected and not approved: applied anyway
    assert actuator.applied == ["act_t_1"]
    [record] = executor.history()
    assert record.status == "applied"
    assert "V2: applied without the twin" in record.note
    assert record.verdict.accepted is False  # the twin's opinion stays on record (H2)


def test_v2_keeps_rate_limits_and_rollback(tmp_path: Path) -> None:
    worse = GOOD.model_copy(update={"loss_pct": 5.0})
    executor, _actuator, kpis, clock = _v2_executor(tmp_path, FakeKpis(after=worse))
    first, second = _action(1, "set_ap_channel"), _action(2, "set_ap_channel", ap="ap1", channel=11)
    for a in (first, second):
        executor.record([a], [_verdict(a, accepted=False)])
    _apply(executor, kpis, clock, [first.action_id])
    with pytest.raises(ExecutorError, match="ap1"):  # 1 high-impact action per AP per 2 min
        executor.apply([second.action_id], STATE)
    clock.advance(30)
    assert executor.check() == [("act_t_1", "rolled_back")]


def test_without_the_switch_nothing_unverified_applies(tmp_path: Path) -> None:
    executor, actuator, _, _ = _executor(tmp_path)  # the default: unverified_ok=False
    action = _action(1, "set_ap_channel")
    executor.record([action], [_verdict(action, accepted=False)])
    with pytest.raises(ExecutorError, match="rejected"):
        executor.apply([action.action_id], STATE)
    assert actuator.applied == []


# ---------------------------------------------------------------- the action's own transient


class TransientKpis(FakeKpis):
    """Worse only while the action settles (a steer re-associates for ~5 s), fine afterwards."""

    def __init__(self, settle_s: float) -> None:
        super().__init__()
        self.settle_s = settle_s
        self.after_windows: list[tuple[datetime, datetime]] = []

    def window(self, start: datetime, end: datetime) -> KPIValues | None:
        if self.applied_at is None or end <= self.applied_at:
            return GOOD
        self.after_windows.append((start, end))
        settling = start < self.applied_at + timedelta(seconds=self.settle_s)
        return GOOD.model_copy(update={"loss_pct": 30.0}) if settling else GOOD


def test_the_watch_skips_the_actions_own_settling_transient(tmp_path: Path) -> None:
    kpis = TransientKpis(CONFIG.settle_s)
    executor, _actuator, _, clock = _executor(tmp_path, kpis=kpis)
    action = _action(1, "steer_clients")
    executor.record([action], [_verdict(action, needs_approval=False)])
    _apply(executor, kpis, clock, [action.action_id])
    clock.advance(30)
    assert executor.check() == [("act_t_1", "kept")]  # the re-association blip is not a regression
    assert kpis.after_windows == [(T0 + timedelta(seconds=10), T0 + timedelta(seconds=30))]


def test_settling_may_not_swallow_the_watch(tmp_path: Path) -> None:
    raw = yaml.safe_load((ROOT / "config" / "executor.yaml").read_text())
    with pytest.raises(ValueError, match="settle_s"):
        load_executor_config(raw | {"settle_s": 20})  # more than half of the 30 s watch (N-6)
