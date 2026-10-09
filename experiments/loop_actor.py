"""P4.5 / P6: the control loop played alongside a batch run (experiments/run_batch.py, loop_mode).

Builds the live loop (api/loop.py) for one run: the twin syncs from that run's telemetry, the
executor drives the AP agent and watches that run's KPIs, and its ledger is kept with the run's
files (<run_dir>/actions.db). Batch runs are evaluation runs, so V2 is allowed here (ADR-005);
every loop event is logged to <run_dir>/loop.jsonl.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from api.loop import Loop, load_loop_config
from common.influx import InfluxConnection
from controller.executor.actuator import AgentActuator
from controller.executor.executor import Executor, load_executor_config
from controller.executor.ledger import Ledger
from controller.executor.live_kpis import InfluxKpis
from ml.optimizer.heuristics import load_heuristic_config
from telemetry.collector.collector import CollectorConfig
from twin.radio import load_radio_params
from twin.sim.analytical import load_sim_params
from twin.state.builder import load_campus_aps
from twin.state.sync import TwinSync, load_sync_config
from twin.verify.verifier import VerifyContext, load_verify_config

log = logging.getLogger("experiments.loop_actor")
ROOT = Path(__file__).resolve().parents[1]


def _yaml(name: str) -> Any:  # Any: parsed YAML, validated by each config loader
    return yaml.safe_load((ROOT / "config" / name).read_text())


class LoopActor:
    """Ticks the loop every period while a batch run plays."""

    def __init__(self, run_id: str, mode: str, run_dir: Path, agent: CollectorConfig) -> None:
        config = load_loop_config(_yaml("loop.yaml") | {"mode": mode, "evaluation": True})
        campus_raw = _yaml("campus_v1.yaml")
        campus, radio = load_campus_aps(campus_raw), load_radio_params(campus_raw)
        conn = InfluxConnection.from_env()
        executor_config = load_executor_config(_yaml("executor.yaml"))
        if config.mode == "V2":
            executor_config = dataclasses.replace(executor_config, unverified_ok=True)  # ADR-005
        executor = Executor(
            Ledger(run_dir / "actions.db"),
            AgentActuator(f"http://{agent.vm_host}:{agent.agent_port}"),
            InfluxKpis(conn, run_id),
            executor_config,
        )
        sync = TwinSync(conn, campus, run_id, load_sync_config(_yaml("twin.yaml")))
        context = VerifyContext(
            campus,
            radio,
            load_sim_params(_yaml("sim.yaml")),
            load_verify_config(_yaml("verify.yaml")),
        )
        self._loop = Loop(
            config, sync.refresh, executor, context, load_heuristic_config(_yaml("optimizer.yaml"))
        )
        self._period, self._next, self._log = config.period_s, 0.0, run_dir / "loop.jsonl"

    def tick(self, elapsed_s: float) -> None:
        """One loop tick each period (a failing tick is logged; the run goes on)."""
        if elapsed_s < self._next:
            return
        self._next = elapsed_s + self._period
        try:
            events = self._loop.tick()
        except Exception:  # the batch run must finish even if one tick fails
            log.exception("loop tick at %.0f s failed", elapsed_s)
            return
        with self._log.open("a") as f:
            for action_id, outcome in events:
                line = {"utc": datetime.now(UTC).isoformat(), "elapsed_s": round(elapsed_s, 1)}
                f.write(json.dumps(line | {"action_id": action_id, "outcome": outcome}) + "\n")
                log.info("loop %.0f s: %s %s", elapsed_s, action_id, outcome)
