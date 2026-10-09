"""Batch runner (experiments/run_batch.py): a run's helpers fail before the VM starts."""

from __future__ import annotations

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
