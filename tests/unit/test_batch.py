"""P2.3 batch planning (experiments/batch.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from experiments.batch import (
    BatchConfig,
    RunPlan,
    host_slept,
    load_batch_config,
    load_scenario,
    plan_runs,
    remote_command,
    run_ok,
)

ROOT = Path(__file__).resolve().parents[2]
RAW: dict[str, Any] = yaml.safe_load((ROOT / "experiments" / "batch_v1.yaml").read_text())


def test_shipped_batch_config_loads() -> None:
    assert load_batch_config(RAW) == BatchConfig(
        dataset_version="v1",
        scenarios=("normal", "lecture_flash_crowd", "ap_failure", "cochannel_interference"),
        seeds={42: "train", 43: "val", 44: "test"},
        agent_wait_s=180.0,
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"scenarios": []}, "scenarios"),
        ({"scenarios": ["normal", "normal"]}, "scenarios"),
        ({"scenarios": ["../etc/passwd"]}, "scenarios"),
        ({"seeds": {42: "train", 43: "holdout"}}, "split"),
        ({"seeds": {"x": "train"}}, "seed"),
        ({"seeds": {}}, "seeds"),
        ({"dataset_version": "v 1"}, "dataset_version"),
        ({"agent_wait_s": 0}, "agent_wait_s"),
        ({"extra": 1}, "unknown"),
    ],
)
def test_bad_batch_config_is_rejected(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_batch_config({**RAW, **change})


def test_every_scenario_runs_with_every_seed_in_a_stable_order() -> None:
    plan = plan_runs(load_batch_config(RAW))
    assert len(plan) == 12
    assert plan[0] == RunPlan("normal-s42", "normal", 42, "train")
    assert plan[-1] == RunPlan("cochannel_interference-s44", "cochannel_interference", 44, "test")
    assert {p.split for p in plan if p.scenario == "ap_failure"} == {"train", "val", "test"}


def test_remote_command_runs_the_scenario_with_its_seed() -> None:
    run = RunPlan("ap_failure-s43", "ap_failure", 43, "val")
    command = remote_command(run, git_commit="abc1234")
    assert command.startswith(
        "RYU_APP=controller.apps.twin_controller RYU_STARTUP_S=5 TIMEOUT_S=1200 "
        "~/Digital-Twin-SDN/testbed/run_on_vm.sh batch-ap_failure-s43 testbed.run_scenario "
    )
    assert command.endswith(
        "experiments/scenarios/ap_failure.yaml --run-id ap_failure-s43 --seed 43 "
        "--git-commit abc1234"
    )


@pytest.mark.parametrize(
    ("wall_s", "monotonic_s", "slept"),
    [(600.0, 600.0, False), (604.0, 600.0, False), (1523.0, 600.0, True)],
)
def test_host_sleep_shows_as_wall_time_running_ahead(
    wall_s: float, monotonic_s: float, slept: bool
) -> None:
    # macOS: time.monotonic() stops while the Mac sleeps, time.time() does not
    assert host_slept(wall_s, monotonic_s) is slept


def test_scenarios_load_from_the_scenario_folder() -> None:
    scenario = load_scenario("ap_failure")
    assert (scenario.scenario_id, scenario.duration_s) == ("ap_failure", 600.0)


@pytest.mark.parametrize(
    ("report", "ok"),
    [
        ({"passed": True, "scenario_ok": True}, True),
        ({"passed": True, "scenario_ok": False}, False),
        ({"passed": False, "scenario_ok": True}, False),
        ({"run_id": "x"}, False),
    ],
)
def test_a_run_is_usable_only_if_scenario_and_collector_passed(
    report: dict[str, Any], ok: bool
) -> None:
    assert run_ok(report) is ok
