"""Dataset export (experiments/export_dataset.py): the run clock and the applied actions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from common.schemas import ACTION_ADAPTER, KPIValues, Verdict
from controller.executor.ledger import Ledger
from experiments.export_dataset import ledger_actions, scenario_start

T0 = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)


def _events(run_dir: Path, starts: list[datetime]) -> None:
    lines = [{"kind": "started", "utc": t.isoformat(), "t": 0.0} for t in starts]
    (run_dir / "events.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))


def test_the_last_started_event_is_the_runs_clock(tmp_path: Path) -> None:
    # a killed earlier attempt left its own `started` line in the same run directory
    _events(tmp_path, [T0, T0 + timedelta(seconds=204)])
    assert scenario_start(tmp_path) == T0 + timedelta(seconds=204)


def test_applied_actions_come_from_the_ledger_with_their_apply_time(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "actions.db")
    kpis = KPIValues(throughput_mbps=1, latency_ms=1, loss_pct=0, jain=1)
    for n, accepted in ((1, True), (2, False)):
        action = ACTION_ADAPTER.validate_python(
            {
                "action_id": f"act_e_{n}",
                "type": "set_qos_queue",
                "source": "operator",
                "reason": "test",
                "created_at": T0,
                "params": {"match": {"zone": "lab"}, "queue_id": 1},
            }
        )
        ledger.add(
            [action],
            [
                Verdict(
                    action_id=action.action_id,
                    accepted=accepted,
                    predicted=kpis,
                    baseline=kpis,
                    violations=[] if accepted else ["x"],
                    impact="low",
                    needs_approval=False,
                    sim_mode="analytical",
                    sim_time_ms=1,
                )
            ],
            T0,
        )
    ledger.update("act_e_1", "applied", T0, applied_at=T0 + timedelta(seconds=120.5))
    [entry] = ledger_actions(ledger, "normal-s45", T0)  # act_e_2 was rejected, never applied
    assert entry["run_id"] == "normal-s45"
    assert entry["t_s"] == 120.5  # when it was applied, not when the log line was written
    assert entry["action"]["action_id"] == "act_e_1"
