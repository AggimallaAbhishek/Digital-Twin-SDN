"""P4.5 / P6: the control loop played alongside a batch run (experiments/run_batch.py, loop_mode).

Builds the live loop (api/loop.py) for one run: the twin syncs from that run's telemetry, the
executor drives the AP agent and watches that run's KPIs, and its ledger is kept with the run's
files (<run_dir>/actions.db). Batch runs are evaluation runs, so V2 is allowed here (ADR-005);
every loop event is logged to <run_dir>/loop.jsonl.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from api.loop import Loop, load_loop_config
from api.wiring import build_executor, build_twin, load_yaml
from common.influx import InfluxConnection
from ml.optimizer.heuristics import load_heuristic_config

log = logging.getLogger("experiments.loop_actor")
ROOT = Path(__file__).resolve().parents[1]


class LoopActor:
    """Ticks the loop every period while a batch run plays."""

    def __init__(self, run_id: str, mode: str, run_dir: Path) -> None:
        config = load_loop_config(load_yaml("loop.yaml") | {"mode": mode, "evaluation": True})
        conn = InfluxConnection.from_env()
        twin = build_twin(conn, run_id)
        v2 = config.mode == "V2"  # ADR-005: evaluation runs only
        executor = build_executor(conn, run_id, run_dir / "actions.db", unverified_ok=v2)
        heuristics = load_heuristic_config(load_yaml("optimizer.yaml"))
        self._loop = Loop(config, twin.sync.refresh, executor, twin.context, heuristics)
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
