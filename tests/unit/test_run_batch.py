"""Batch runner (experiments/run_batch.py): a run's helpers fail before the VM starts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from experiments import run_batch
from experiments.batch import RunPlan
from experiments.validation_actions import ActionStep


def test_a_helper_that_cannot_start_stops_the_run_before_the_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[Any] = []

    def broken(*args: Any) -> Any:
        raise ValueError("executor config: unknown keys ['settle_s']")

    monkeypatch.setattr(run_batch, "_actor", broken)
    monkeypatch.setattr(run_batch, "run", lambda *a, **k: None)  # make vm-clock
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a))
    plan = RunPlan("normal-s46", "normal", 46, "test")
    extras = run_batch.RunExtras(steps=[ActionStep(120, "heuristic", {})])
    with pytest.raises(ValueError, match="settle_s"):
        run_batch.play(plan, tmp_path, 1.0, "abc", extras)
    assert started == []  # no scenario was started on the VM, so none is left orphaned


def test_a_run_that_crashes_is_recorded_and_the_batch_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # P6.4: a crash is a failed run on record (batch.json, collector.json), then re-run+logged
    config = tmp_path / "batch.yaml"
    config.write_text(
        "dataset_version: evalv2-v1\nscenarios: [ap_failure]\nseeds: {42: train, 43: val}\n"
        "agent_wait_s: 1\nrun_tag: v2\nloop_mode: V2\n"
    )
    monkeypatch.setattr(run_batch, "ROOT", tmp_path)
    monkeypatch.setattr(run_batch, "git_commit", lambda: "abc")
    monkeypatch.setattr(run_batch, "inputs_hash", lambda *a: "h")

    def crash(plan: RunPlan, *args: Any) -> dict[str, Any]:
        if plan.seed == 42:
            raise RuntimeError("ssh: connection reset")
        return {"passed": True, "scenario_ok": True}

    monkeypatch.setattr(run_batch, "play", crash)
    assert run_batch.main(["--config", str(config)]) == 1
    out = tmp_path / "data" / "raw" / "evalv2-v1"
    runs = json.loads((out / "batch.json").read_text())["runs"]
    assert [(r["seed"], r["passed"]) for r in runs] == [(42, False), (43, True)]
    crashed = json.loads((out / "ap_failure-v2-s42" / "collector.json").read_text())
    assert "connection reset" in crashed["error"]
    monkeypatch.setattr(run_batch, "play", lambda *a: {"passed": True, "scenario_ok": True})
    monkeypatch.setattr(run_batch, "is_done", lambda d: (d / "ok").exists())
    run_batch.main(["--config", str(config)])  # the crashed run is kept, logged, run again
    [line] = (out / "reruns.jsonl").read_text().splitlines()
    assert json.loads(line)["run_id"] == "ap_failure-v2-s42"


def test_a_failed_attempt_is_kept_and_logged_before_its_rerun(tmp_path: Path) -> None:
    # P6.4 Done when: "failed runs re-run and logged" (decision P6.4-A)
    out = tmp_path / "evalv2-v1"
    run_dir = out / "ap_failure-v2-s43"
    run_dir.mkdir(parents=True)
    (run_dir / "collector.json").write_text('{"passed": false, "error": "agent never answered"}')
    kept = run_batch.keep_failed_attempt(run_dir, "2026-10-20T10:00:00Z")
    assert kept == tmp_path / "evalv2-v1-attempts" / "ap_failure-v2-s43-1"
    assert (kept / "collector.json").exists()
    assert not run_dir.exists()  # the rerun starts from an empty run folder
    [line] = (out / "reruns.jsonl").read_text().splitlines()
    assert json.loads(line) == {
        "run_id": "ap_failure-v2-s43",
        "at": "2026-10-20T10:00:00Z",
        "attempt": str(kept),
        "collector": {"passed": False, "error": "agent never answered"},
    }
    run_dir.mkdir()  # a second failure is attempt 2, not a clash
    assert run_batch.keep_failed_attempt(run_dir, "2026-10-20T11:00:00Z").name.endswith("-2")
