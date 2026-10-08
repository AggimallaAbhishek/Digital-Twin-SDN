"""P4.4 action executor: applies only verified actions, watches them, rolls back (PROJECT_PLAN §8).

    executor = Executor(Ledger(path), actuator, live_kpis, load_executor_config(raw))
    executor.record(actions, verdicts)        # the verifier's joint verdicts (one set)
    executor.approve(action_id, by="abhishek")  # operator, for actions that need it
    executor.apply(action_ids, state)         # the whole set, or nothing
    executor.check()                          # every loop: keep or roll back what was watched

Safety rules (RULEBOOK T-5, N-6; none can be switched off):
- No accepted verdict -> refused. Rejected -> refused. Applied once only.
- `needs_approval` (high impact; medium until P3.5) -> refused until an operator approves.
- A verified set is applied whole: if one action fails, those already applied are reverted.
- Rate limits: at most 1 high-impact action per AP per `high_impact_per_ap_s`, at most
  `max_actions_per_loop` actions per `loop_s`.
- After `watch_s`, the live KPIs over the watch window are compared with the window before the
  apply. A KPI worse by more than `regression_pct` percent **and** by more than its noise floor
  (decision P4.4-B) rolls the whole set back, last action first. No live KPIs -> roll back:
  nothing shows the action is safe.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from common.schemas import Action, KPIValues, Verdict, impact_of
from controller.executor.ledger import ActionRecord, Event, Ledger
from twin.state.model import TwinState

_KPIS = ("throughput_mbps", "latency_ms", "loss_pct", "jain")
_LOWER_IS_BETTER = {"latency_ms", "loss_pct"}
_DONE = {"applied", "kept", "rolled_back", "failed", "rollback_failed"}


class ExecutorError(RuntimeError):
    """The executor refused or could not complete a request; the message says why."""


class Actuator(Protocol):
    """Changes the network (controller/executor/actuator.py over the AP agent)."""

    def apply(self, action: Action, state: TwinState) -> dict[str, Any]:  # Any: JSON config
        """Apply `action`; return what is needed to revert it."""
        ...

    def revert(self, action: Action, previous: dict[str, Any]) -> None:  # Any: JSON config
        """Put back the configuration `apply` returned."""
        ...


class LiveKpis(Protocol):
    """Measured network KPIs (controller/executor/live_kpis.py over InfluxDB)."""

    def window(self, start: datetime, end: datetime) -> KPIValues | None:
        """KPIs over [start, end); None if there is no telemetry in it."""
        ...


@dataclass(frozen=True)
class ExecutorConfig:
    """config/executor.yaml."""

    watch_s: float
    regression_pct: float
    noise_floor: Mapping[str, float]
    high_impact_per_ap_s: float
    max_actions_per_loop: int
    loop_s: float


# (key, smallest, largest): anything outside would switch a safety rule off in practice (N-6)
_LIMITS = (
    ("watch_s", 1, 300),
    ("regression_pct", 1, 50),
    ("high_impact_per_ap_s", 60, 3600),
    ("max_actions_per_loop", 1, 10),
    ("loop_s", 1, 60),
)


def load_executor_config(raw: Mapping[str, Any]) -> ExecutorConfig:
    """Validate config/executor.yaml; ValueError names the field."""
    known = {"noise_floor", *(k for k, _, _ in _LIMITS)}
    if set(raw) - known:
        raise ValueError(f"executor config: unknown keys {sorted(set(raw) - known)}")
    for key, low, high in _LIMITS:
        value = raw.get(key)
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not low <= value <= high
        ):
            raise ValueError(f"{key} must be a number in [{low}, {high}], got {value!r}")
    floor = raw.get("noise_floor")
    if not isinstance(floor, Mapping) or set(floor) != set(_KPIS):
        raise ValueError(f"noise_floor needs exactly {list(_KPIS)}")
    if any(not isinstance(v, int | float) or v < 0 for v in floor.values()):
        raise ValueError("noise_floor values must be numbers >= 0")
    return ExecutorConfig(
        watch_s=float(raw["watch_s"]),
        regression_pct=float(raw["regression_pct"]),
        noise_floor={k: float(v) for k, v in floor.items()},
        high_impact_per_ap_s=float(raw["high_impact_per_ap_s"]),
        max_actions_per_loop=int(raw["max_actions_per_loop"]),
        loop_s=float(raw["loop_s"]),
    )


class Executor:
    """The only component that changes the network, and only for verified actions."""

    def __init__(
        self,
        ledger: Ledger,
        actuator: Actuator,
        kpis: LiveKpis,
        config: ExecutorConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ledger, self._actuator, self._kpis = ledger, actuator, kpis
        self._config, self._clock = config, clock

    def record(self, actions: Sequence[Action], verdicts: Sequence[Verdict]) -> None:
        """Store the verifier's verdicts for one set of actions."""
        if not actions or [a.action_id for a in actions] != [v.action_id for v in verdicts]:
            raise ExecutorError("each action needs its own verdict, in the same order")
        known = [a.action_id for a in actions if self._ledger.get(a.action_id) is not None]
        if known:
            raise ExecutorError(f"already recorded: {', '.join(known)} (action ids are unique)")
        self._ledger.add(actions, verdicts, self._clock())

    def approve(self, action_id: str, by: str) -> None:
        """An operator's approval for an action that needs one."""
        record = self._get(action_id)
        if record.status == "rejected":
            raise ExecutorError(f"{action_id} was rejected by the twin")
        if not record.verdict.needs_approval:
            raise ExecutorError(f"{action_id} does not need approval")
        if record.status != "verified":
            raise ExecutorError(f"{action_id} is {record.status}")
        self._ledger.update(action_id, "approved", self._clock(), f"by {by}", approved_by=by)

    def apply(self, action_ids: Sequence[str], state: TwinState) -> None:
        """Apply a verified set (all its actions, in order), or raise ExecutorError."""
        records = [self._get(a) for a in action_ids]
        self._check_applicable(records)
        now = self._clock()
        self._check_rate_limits(records, now)
        baseline = self._kpis.window(now - timedelta(seconds=self._config.watch_s), now)
        done: list[tuple[ActionRecord, dict[str, Any]]] = []
        for record in records:
            try:
                done.append((record, self._actuator.apply(record.action, state)))
            except Exception as exc:  # any failure: undo the part of the set already applied
                self._revert(done, now, "failed", f"the set did not apply: {exc}")
                for r in records[len(done) :]:
                    self._ledger.update(r.action_id, "failed", now, f"not applied: {exc}")
                raise ExecutorError(f"{record.action_id}: {exc}") from exc
        for record, previous in done:
            self._ledger.update(
                record.action_id,
                "applied",
                now,
                previous=previous,
                baseline=baseline,
                applied_at=now,
            )

    def check(self) -> list[tuple[str, str]]:
        """Finish every watch that is due: (action_id, kept | rolled_back) for each action."""
        now = self._clock()
        watch = timedelta(seconds=self._config.watch_s)
        outcome: list[tuple[str, str]] = []
        due = {
            r.group_id
            for r in self._ledger.records("applied")
            if r.applied_at is not None and r.applied_at + watch <= now
        }
        for group_id in sorted(due):
            members = [r for r in self._ledger.group(group_id) if r.status == "applied"]
            applied_at = members[0].applied_at
            assert applied_at is not None  # noqa: S101 - selected above for having applied_at
            after = self._kpis.window(applied_at, applied_at + watch)
            problems = _regressions(members[0].baseline, after, self._config)
            if problems:
                pairs = [(r, r.previous or {}) for r in members]
                self._revert(pairs, now, "rolled_back", "; ".join(problems))
            else:
                for r in members:
                    self._ledger.update(r.action_id, "kept", now, "KPIs held during the watch")
            final = {r.action_id: r.status for r in self._ledger.group(group_id)}
            outcome += [(r.action_id, final[r.action_id]) for r in members]
        return outcome

    def group_of(self, action_id: str) -> list[str]:
        """Every action verified together with `action_id`, in order (apply takes the set)."""
        return [r.action_id for r in self._ledger.group(self._get(action_id).group_id)]

    def history(self, status: str | None = None) -> list[ActionRecord]:
        """The audit log, oldest first (GET /actions?status=)."""
        return self._ledger.records(status)

    def events(self, action_id: str) -> list[Event]:
        """Every status change of one action."""
        return self._ledger.events(action_id)

    # ------------------------------------------------------------------ rules
    def _get(self, action_id: str) -> ActionRecord:
        record = self._ledger.get(action_id)
        if record is None:
            raise ExecutorError(f"{action_id} has no verdict: simulate it in the twin first")
        return record

    def _check_applicable(self, records: list[ActionRecord]) -> None:
        group = self._ledger.group(records[0].group_id)
        if {r.action_id for r in records} != {r.action_id for r in group} or len(
            {r.group_id for r in records}
        ) > 1:
            raise ExecutorError("apply the whole set the twin verified together")
        for r in records:
            if r.status == "rejected":
                raise ExecutorError(f"{r.action_id} was rejected by the twin")
            if r.status in _DONE:
                raise ExecutorError(f"{r.action_id} was already applied ({r.status})")
            if r.verdict.needs_approval and r.approved_by is None:
                raise ExecutorError(f"{r.action_id} needs operator approval first")

    def _check_rate_limits(self, records: list[ActionRecord], now: datetime) -> None:
        cfg = self._config
        recent = self._ledger.applied_since(now - timedelta(seconds=cfg.loop_s))
        if len(recent) + len(records) > cfg.max_actions_per_loop:
            raise ExecutorError(
                f"at most {cfg.max_actions_per_loop} actions per {cfg.loop_s:g} s loop"
            )
        window = timedelta(seconds=cfg.high_impact_per_ap_s)
        busy = {
            _ap_of(r.action)
            for r in self._ledger.applied_since(now - window)
            if impact_of(r.action) == "high"
        }
        for r in records:
            ap = _ap_of(r.action)
            if impact_of(r.action) == "high" and ap in busy:
                raise ExecutorError(
                    f"{ap} had a high-impact action less than {cfg.high_impact_per_ap_s:g} s ago"
                )

    def _revert(
        self,
        done: list[tuple[ActionRecord, dict[str, Any]]],
        now: datetime,
        status: str,
        note: str,
    ) -> None:
        """Revert `done`, last first; an action whose revert fails is flagged for an operator."""
        for record, previous in reversed(done):
            try:
                self._actuator.revert(record.action, previous)
            except Exception as exc:  # keep reverting the rest; flag this one
                self._ledger.update(
                    record.action_id, "rollback_failed", now, f"{note}; revert failed: {exc}"
                )
            else:
                self._ledger.update(record.action_id, status, now, note)


def _ap_of(action: Action) -> str | None:
    return getattr(action.params, "ap", None)


def _regressions(
    before: KPIValues | None, after: KPIValues | None, config: ExecutorConfig
) -> list[str]:
    """Why the watch failed, or [] if the KPIs held."""
    if before is None or after is None:
        return ["no live KPIs to compare: rolled back to be safe"]
    problems = []
    for kpi in _KPIS:
        was, now = getattr(before, kpi), getattr(after, kpi)
        worse = now - was if kpi in _LOWER_IS_BETTER else was - now
        if worse > config.noise_floor[kpi] and worse > abs(was) * config.regression_pct / 100:
            problems.append(
                f"{kpi} {was:g} -> {now:g} (worse by more than {config.regression_pct:g}%)"
            )
    return problems
