"""P4.5 control loop: observe, propose, verify, apply, watch, roll back (PROJECT_PLAN §4).

    loop = Loop(load_loop_config(raw), sync.refresh, executor, verify_context, heuristics)
    loop.tick()          # every `period_s` (5 s)

Each tick finishes the executor's due watches (keep or roll back), then by mode:

- **V1** plain SDN: nothing else (the controller only learns L2; stations rejoin by themselves).
- **V3** full system: while an applied action is still being watched, propose nothing (one
  change at a time). Otherwise each heuristic proposal (ml/optimizer/heuristics.py) is verified
  in the twin and recorded; accepted ones that need no approval are applied; ones that need an
  operator wait for one (a proposal identical to one already waiting is not recorded again).
- **V2** heuristics without the twin, evaluation only (ADR-005): the twin's verdict is still
  computed and recorded, then the proposal is applied anyway by an executor whose config has
  `unverified_ok`. Rate limits and rollback still hold.

Lives in `api` because it composes twin, ml and the executor (import rules, deviation #13).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from common.schemas import Action
from controller.executor.executor import Executor, ExecutorError
from ml.optimizer.heuristics import HeuristicConfig, propose
from twin.state.model import TwinState
from twin.verify.verifier import VerifyContext, verify

log = logging.getLogger("api.loop")
MODES = ("V1", "V2", "V3")


@dataclass(frozen=True)
class LoopConfig:
    """config/loop.yaml."""

    mode: str
    period_s: float
    evaluation: bool


def load_loop_config(raw: Mapping[str, Any]) -> LoopConfig:
    """Validate config/loop.yaml; V2 only with `evaluation: true` (ADR-005)."""
    unknown = set(raw) - {"mode", "period_s", "evaluation"}
    if unknown:
        raise ValueError(f"loop config: unknown keys {sorted(unknown)}")
    mode, period, evaluation = raw.get("mode"), raw.get("period_s"), raw.get("evaluation")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if not isinstance(period, int | float) or isinstance(period, bool) or period <= 0:
        raise ValueError(f"period_s must be a number > 0, got {period!r}")
    if not isinstance(evaluation, bool):
        raise ValueError(f"evaluation must be true or false, got {evaluation!r}")
    if mode == "V2" and not evaluation:
        raise ValueError("mode V2 applies actions without the twin: only with evaluation: true")
    return LoopConfig(str(mode), float(period), evaluation)


class Loop:
    """One control loop over the twin, the heuristics and the executor."""

    def __init__(
        self,
        config: LoopConfig,
        state: Callable[[], TwinState],
        executor: Executor,
        context: VerifyContext,
        heuristics: HeuristicConfig,
    ) -> None:
        self._config, self._state, self._executor = config, state, executor
        self._context, self._heuristics = context, heuristics
        self._waiting: set[str] = set()  # proposals recorded and waiting for an operator

    def tick(self) -> list[tuple[str, str]]:
        """One loop: (action_id, what happened) for every action touched this tick."""
        events = self._executor.check()
        if self._config.mode == "V1" or self._executor.history("applied"):
            return events
        state = self._state()
        for action in propose(state, self._heuristics, self._context.radio):
            outcome = self._handle(action, state)
            if outcome is not None:
                events.append((action.action_id, outcome))
        return events

    def run(self, stop: threading.Event) -> None:
        """tick() every period_s until `stop` is set; a failing tick is logged, not fatal."""
        while not stop.is_set():
            try:
                for action_id, outcome in self.tick():
                    log.info("loop %s: %s %s", self._config.mode, action_id, outcome)
            except Exception:  # keep looping: one bad tick must not stop the control loop
                log.exception("loop tick failed")
            stop.wait(self._config.period_s)

    def _handle(self, action: Action, state: TwinState) -> str | None:
        signature = f"{action.type}:{action.params.model_dump_json()}"
        if signature in self._waiting:
            return None
        [verdict] = verify(state, [action], self._context)
        try:
            self._executor.record([action], [verdict])
        except ExecutorError:  # same state as an earlier tick (stalled telemetry): handled then
            return None
        v2 = self._config.mode == "V2"
        if not v2 and not verdict.accepted:
            return "rejected"
        if not v2 and verdict.needs_approval:
            self._waiting.add(signature)
            return "awaiting approval"
        try:
            self._executor.apply([action.action_id], state)
        except ExecutorError as exc:  # a rate limit: the next tick may try again
            return f"not applied: {exc}"
        return "applied"
