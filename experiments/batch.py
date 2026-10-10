"""P2.3 batch planning: which runs make up a dataset, and the VM command for each.

Pure apart from `load_scenario` (reads one YAML file); experiments/run_batch.py executes the
plan. Split by run (RULEBOOK E-2): the config maps each seed to one split, so a run's rows all
land in the same split.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from common.schemas import Scenario

SPLITS = ("train", "val", "test")
SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
_KEYS = {
    "dataset_version",
    "scenarios",
    "seeds",
    "agent_wait_s",
    "run_tag",
    "loop_mode",
    "genai_eval",
}
LOOP_MODES = ("V1", "V2", "V3")  # P4.5 / P6 variants
_NAME = re.compile(r"^[a-z0-9_]+$")
_VERSION = re.compile(r"^([a-z][a-z0-9]*-)?v[0-9]+$")  # v1, or with a purpose: actions-v1
_TAG = re.compile(r"^[a-z0-9]+$")
# Same environment as `make scenario-vm`; 1200 s covers a 10-min scenario plus setup.
_VM_ENV = "RYU_APP=controller.apps.twin_controller RYU_STARTUP_S=5 TIMEOUT_S=1200"
_RUN_ON_VM = "~/Digital-Twin-SDN/testbed/run_on_vm.sh"


@dataclass(frozen=True)
class BatchConfig:
    """experiments/batch_v1.yaml."""

    dataset_version: str
    scenarios: tuple[str, ...]
    seeds: dict[int, str]  # seed -> split
    agent_wait_s: float
    run_tag: str | None = None  # in every run id: scenario-<tag>-s<seed>
    loop_mode: str | None = None  # P4.5 loop variant played alongside each run
    genai_eval: bool = False  # P5.5 / P5.6 copilot and explainer played alongside each run


@dataclass(frozen=True)
class RunPlan:
    """One scenario run of the batch."""

    run_id: str
    scenario: str
    seed: int
    split: str


def load_batch_config(raw: Mapping[str, Any]) -> BatchConfig:
    """Validate a parsed batch YAML; ValueError names the bad field."""
    unknown = set(raw) - _KEYS
    if unknown:
        raise ValueError(f"batch config: unknown keys {sorted(unknown)}")
    version = raw.get("dataset_version")
    if not isinstance(version, str) or not _VERSION.match(version):
        raise ValueError(f"dataset_version must look like v1 or actions-v1, got {version!r}")
    scenarios = raw.get("scenarios")
    if (
        not isinstance(scenarios, list)
        or not scenarios
        or len(set(scenarios)) != len(scenarios)
        or not all(isinstance(s, str) and _NAME.match(s) for s in scenarios)
    ):
        raise ValueError(f"scenarios must be distinct scenario file names, got {scenarios!r}")
    seeds = raw.get("seeds")
    if not isinstance(seeds, dict) or not seeds:
        raise ValueError("seeds must map at least one seed to a split")
    for seed, split in seeds.items():
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError(f"seed must be an integer, got {seed!r}")
        if split not in SPLITS:
            raise ValueError(f"split for seed {seed} must be one of {SPLITS}, got {split!r}")
    wait = raw.get("agent_wait_s")
    if not isinstance(wait, int | float) or isinstance(wait, bool) or wait <= 0:
        raise ValueError(f"agent_wait_s must be a number > 0, got {wait!r}")
    tag, mode = raw.get("run_tag"), raw.get("loop_mode")
    if tag is not None and (not isinstance(tag, str) or not _TAG.match(tag)):
        raise ValueError(f"run_tag must be lowercase letters and digits, got {tag!r}")
    if mode is not None and mode not in LOOP_MODES:
        raise ValueError(f"loop_mode must be one of {LOOP_MODES}, got {mode!r}")
    genai = raw.get("genai_eval", False)
    if not isinstance(genai, bool):
        raise ValueError(f"genai_eval must be true or false, got {genai!r}")
    return BatchConfig(version, tuple(scenarios), dict(seeds), float(wait), tag, mode, genai)


def plan_runs(config: BatchConfig) -> list[RunPlan]:
    """Every scenario with every seed, scenario-major (stable order, resumable by run_id)."""
    return [
        RunPlan(
            f"{scenario}-{config.run_tag}-s{seed}" if config.run_tag else f"{scenario}-s{seed}",
            scenario,
            seed,
            split,
        )
        for scenario in config.scenarios
        for seed, split in config.seeds.items()
    ]


def remote_command(run: RunPlan, git_commit: str) -> str:
    """Shell command (on the VM, via ssh) that plays one run of the batch."""
    return (
        f"{_VM_ENV} {_RUN_ON_VM} batch-{run.run_id} testbed.run_scenario "
        f"experiments/scenarios/{run.scenario}.yaml --run-id {run.run_id} --seed {run.seed} "
        f"--git-commit {git_commit}"
    )


SLEEP_TOLERANCE_S = 5.0


def host_slept(wall_elapsed_s: float, monotonic_elapsed_s: float) -> bool:
    """True if the Mac slept during a run: on macOS the monotonic clock stops in sleep, the
    wall clock does not. A sleeping Mac pauses the VM too, so such a run is not usable data
    (docs/setup.md Known problems #13)."""
    return wall_elapsed_s - monotonic_elapsed_s > SLEEP_TOLERANCE_S


def load_scenario(name: str) -> Scenario:
    """experiments/scenarios/<name>.yaml, validated against common/schemas.py."""
    return Scenario.model_validate(yaml.safe_load((SCENARIOS_DIR / f"{name}.yaml").read_text()))


def run_ok(report: Mapping[str, Any]) -> bool:
    """A batch run is usable data: the scenario finished and the collector's checks passed."""
    return bool(report.get("passed")) and bool(report.get("scenario_ok"))
