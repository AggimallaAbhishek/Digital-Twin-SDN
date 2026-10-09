"""P3.5 validation batch, live part: applies a run's scheduled steps through the real pipeline.

At each due step: rebuild the twin state from InfluxDB (twin/state/sync.py), turn the step into
actions (experiments/validation_actions.py), have the verifier judge them together, record the
verdicts in the executor, approve the ones that need it as the batch's operator, and apply the
set only if every verdict accepted it. The executor's watch and rollback stay on. Every step is
logged to <run_dir>/actions.jsonl with its UTC time, whether it was applied, and why not.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from common.influx import InfluxConnection
from controller.executor.actuator import AgentActuator
from controller.executor.executor import Executor, ExecutorError, load_executor_config
from controller.executor.ledger import Ledger
from controller.executor.live_kpis import InfluxKpis
from experiments.validation_actions import ActionStep, actions_for
from ml.optimizer.heuristics import load_heuristic_config
from telemetry.collector.collector import CollectorConfig
from twin.radio import load_radio_params
from twin.sim.analytical import load_sim_params
from twin.state.builder import load_campus_aps
from twin.state.sync import TwinSync, load_sync_config
from twin.verify.verifier import VerifyContext, load_verify_config, verify

log = logging.getLogger("experiments.validation_actor")
ROOT = Path(__file__).resolve().parents[1]
OPERATOR = "validation-batch"


def _yaml(name: str) -> Any:  # Any: parsed YAML, validated by each config loader
    return yaml.safe_load((ROOT / "config" / name).read_text())


class Actor:
    """Applies one run's scheduled steps when they fall due."""

    def __init__(
        self, run_id: str, steps: list[ActionStep], run_dir: Path, agent: CollectorConfig
    ) -> None:
        campus_raw = _yaml("campus_v1.yaml")
        campus = load_campus_aps(campus_raw)
        self._radio = load_radio_params(campus_raw)
        conn = InfluxConnection.from_env()
        self._run_id, self._steps, self._log = run_id, list(steps), run_dir / "actions.jsonl"
        self._sync = TwinSync(conn, campus, run_id, load_sync_config(_yaml("twin.yaml")))
        self._context = VerifyContext(
            campus,
            self._radio,
            load_sim_params(_yaml("sim.yaml")),
            load_verify_config(_yaml("verify.yaml")),
        )
        self._heuristics = load_heuristic_config(_yaml("optimizer.yaml"))
        self._executor = Executor(
            Ledger(run_dir / "actions.db"),
            AgentActuator(f"http://{agent.vm_host}:{agent.agent_port}"),
            InfluxKpis(conn, run_id),
            load_executor_config(_yaml("executor.yaml")),
        )

    def tick(self, elapsed_s: float) -> None:
        """Run every step due by `elapsed_s` seconds into the scenario; finish due watches."""
        while self._steps and self._steps[0].at_s <= elapsed_s:
            self._do(self._steps.pop(0))
        for action_id, status in self._executor.check():
            log.info("%s: %s %s", self._run_id, action_id, status)

    def _do(self, step: ActionStep) -> None:
        state = self._sync.refresh()
        actions = actions_for(step, state, self._radio, self._heuristics, self._run_id)
        if not actions:
            self._write(step, None, False, "no action for this state")
            return
        verdicts = verify(state, actions, self._context)
        self._executor.record(actions, verdicts)
        note, applied = "", False
        if all(v.accepted for v in verdicts):
            try:
                for a, v in zip(actions, verdicts, strict=True):
                    if v.needs_approval:
                        self._executor.approve(a.action_id, by=OPERATOR)
                self._executor.apply([a.action_id for a in actions], state)
                applied = True
            except ExecutorError as exc:
                note = str(exc)
        else:
            note = "; ".join(x for v in verdicts for x in v.violations)
        for action in actions:
            self._write(step, action.model_dump(mode="json", by_alias=True), applied, note)

    def _write(self, step: ActionStep, action: object, applied: bool, note: str) -> None:
        line = {
            "run_id": self._run_id,
            "utc": datetime.now(UTC).isoformat(),
            "step_at_s": step.at_s,
            "step": step.type,
            "applied": applied,
            "note": note,
            "action": action,
        }
        with self._log.open("a") as f:
            f.write(json.dumps(line) + "\n")
        log.info(
            "%s: step %s at %g s -> applied=%s %s",
            self._run_id,
            step.type,
            step.at_s,
            applied,
            note,
        )
