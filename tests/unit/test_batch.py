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


@pytest.mark.parametrize("version", ["v2", "actions-v1"])
def test_a_dataset_version_may_carry_a_purpose_prefix(version: str) -> None:
    raw = yaml.safe_load((ROOT / "experiments" / "batch_v1.yaml").read_text())
    assert load_batch_config(raw | {"dataset_version": version}).dataset_version == version


@pytest.mark.parametrize("version", ["actions", "-v1", "Actions-v1", "actions-v1/../x"])
def test_other_dataset_versions_are_refused(version: str) -> None:
    raw = yaml.safe_load((ROOT / "experiments" / "batch_v1.yaml").read_text())
    with pytest.raises(ValueError, match="dataset_version"):
        load_batch_config(raw | {"dataset_version": version})


def test_a_run_tag_and_loop_mode_name_the_runs_of_a_loop_batch() -> None:
    raw = yaml.safe_load((ROOT / "experiments" / "batch_v1.yaml").read_text())
    config = load_batch_config(
        raw | {"dataset_version": "loopv3-v1", "run_tag": "v3", "loop_mode": "V3"}
    )
    assert (config.run_tag, config.loop_mode) == ("v3", "V3")
    assert plan_runs(config)[0].run_id == "normal-v3-s42"


def test_without_a_tag_run_ids_are_unchanged() -> None:
    raw = yaml.safe_load((ROOT / "experiments" / "batch_v1.yaml").read_text())
    config = load_batch_config(raw)
    assert (config.run_tag, config.loop_mode) == (None, None)
    assert config.genai_eval is False
    assert plan_runs(config)[0].run_id == "normal-s42"


def test_the_genai_batch_plays_the_genai_eval() -> None:
    config = load_batch_config(
        yaml.safe_load((ROOT / "experiments" / "batch_genai_v1.yaml").read_text())
    )
    assert config.genai_eval is True
    assert config.loop_mode is None  # the network is left alone: the copilot only proposes
    assert [r.run_id for r in plan_runs(config)] == [
        "ap_failure-genai-s44",
        "cochannel_interference-genai-s44",
        "lecture_flash_crowd-genai-s44",
    ]


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"run_tag": "V 3"}, "run_tag"),
        ({"loop_mode": "V4"}, "loop_mode"),
        ({"loop_mode": "V0"}, "loop_mode"),
        ({"genai_eval": "yes"}, "genai_eval"),
    ],
)
def test_bad_loop_settings_are_refused(change: dict[str, Any], named: str) -> None:
    raw = yaml.safe_load((ROOT / "experiments" / "batch_v1.yaml").read_text())
    with pytest.raises(ValueError, match=named):
        load_batch_config(raw | change)
