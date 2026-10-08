"""P2.3 batch runner: plays every scenario x seed on the VM with the collector, unattended.

    make batch                                   # experiments/batch_v1.yaml, ~2 h 15 min
    uv run python -m experiments.run_batch --config experiments/batch_v1.yaml

For each run (experiments/batch.py plan_runs): set the VM clock, start the scenario on the VM
(run_on_vm.sh starts with `mn -c`, which resets the network; RULEBOOK N-2), collect telemetry into
InfluxDB until the scenario ends, then copy the run's manifest, events and summary from the VM to
data/raw/<version>/<run_id>/ next to the collector's health report. Resumable: a run whose files
are complete and that passed is skipped. The Mac must stay awake (run under `caffeinate -i`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import yaml

from common.schemas import Scenario
from experiments.batch import RunPlan, host_slept, load_batch_config, plan_runs, remote_command
from experiments.shell import git_commit, run, tool
from telemetry.collector.collector import (
    Collector,
    FetchError,
    InfluxWriter,
    http_fetch,
    load_collector_config,
)
from telemetry.collector.records import Meta

log = logging.getLogger("experiments.run_batch")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "experiments" / "batch_v1.yaml"
VM = "sdnvm"
VM_RUNS = "p02/runs"  # LOG_DIR on the VM (testbed/run_on_vm.sh), relative to the home directory
VM_FILES = ("manifest.json", "events.jsonl", "summary.json")
SSH_TIMEOUT_S = 30
POLL_S = 2.0
MAX_VM_SKEW_S = 2.0  # a VM paused with a sleeping Mac comes back this far behind (or more)
END_MARGIN_S = 2.0  # stop collecting this long before the scenario clock ends (teardown follows)
JOIN_TIMEOUT_S = 10.0  # the collector stops within one poll period of being told to
# a run may take the VM's own timeout (batch.py TIMEOUT_S=1200) plus campus setup and teardown
SCENARIO_TIMEOUT_S = 1200 + 120


def _wait(scenario: subprocess.Popen[bytes], plan: RunPlan) -> None:
    """Wait for the VM run to end; kill the ssh session if it hangs past SCENARIO_TIMEOUT_S."""
    try:
        scenario.wait(timeout=SCENARIO_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log.error("%s: ssh session hung; killed", plan.run_id)
        scenario.kill()
        scenario.wait()


def vm_skew_s() -> float:
    """VM clock minus Mac clock, from one ssh round trip (midpoint of the call)."""
    before = time.time()
    vm = float(run(["ssh", VM, "date +%s.%N"], capture_output=True, check=True).stdout)
    return vm - (before + time.time()) / 2


def inputs_hash(batch_config: Path, scenarios: tuple[str, ...]) -> str:
    """sha256 over the batch config, its scenario files and the campus/traffic config."""
    paths = [
        batch_config,
        *(ROOT / "experiments" / "scenarios" / f"{s}.yaml" for s in scenarios),
        ROOT / "config" / "campus_v1.yaml",
        ROOT / "testbed" / "traffic" / "profiles.yaml",
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()[:16]


def scenario_duration_s(scenario: str) -> float:
    """duration_s of experiments/scenarios/<scenario>.yaml (validated as a Scenario)."""
    path = ROOT / "experiments" / "scenarios" / f"{scenario}.yaml"
    return Scenario.model_validate(yaml.safe_load(path.read_text())).duration_s


def is_done(run_dir: Path) -> bool:
    """The run's files are all here and both the scenario and the collector passed."""
    if not all((run_dir / name).exists() for name in (*VM_FILES, "collector.json")):
        return False
    collector = json.loads((run_dir / "collector.json").read_text())
    return bool(collector.get("passed")) and bool(collector.get("scenario_ok"))


def wait_for_agent(url: str, timeout_s: float, scenario: subprocess.Popen[bytes]) -> bool:
    """True once the AP agent answers; False if it doesn't in time or the scenario ended."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and scenario.poll() is None:
        try:
            http_fetch(url, timeout_s=1.0)
            return True
        except FetchError:
            time.sleep(POLL_S)
    return False


def play(plan: RunPlan, run_dir: Path, agent_wait_s: float, commit: str) -> dict[str, Any]:
    """One run: scenario on the VM + collector on the Mac. Returns the collector report."""
    run(["make", "--no-print-directory", "vm-clock"], cwd=ROOT, check=True)
    wall0, mono0 = time.time(), time.monotonic()
    ssh = [tool("ssh"), VM, remote_command(plan, commit)]
    scenario = subprocess.Popen(ssh)  # noqa: S603 - fixed argv, no shell
    config = load_collector_config()
    agent = f"http://{config.vm_host}:{config.agent_port}/aps"
    report: dict[str, Any] = {"run_id": plan.run_id, "split": plan.split, "passed": False}
    if wait_for_agent(agent, agent_wait_s, scenario):
        collector = Collector(
            config, Meta(plan.scenario, plan.run_id), http_fetch, InfluxWriter.from_env(config)
        )
        stop = threading.Event()
        thread = threading.Thread(target=collector.run, args=(None, stop), daemon=True)
        thread.start()
        # The scenario clock starts just after the agent answers: stop collecting before the
        # VM tears the network down, so teardown is not counted as a gap.
        end = time.monotonic() + scenario_duration_s(plan.scenario) - END_MARGIN_S
        while scenario.poll() is None and time.monotonic() < end:
            time.sleep(POLL_S / 4)
        stop.set()
        thread.join(timeout=JOIN_TIMEOUT_S)
        _wait(scenario, plan)
        health = collector.health
        health.finish(at=time.time())
        report |= {
            "passed": health.passed(config.max_lag_s, config.max_gap_s),
            "records": health.records,
            "backlog_records": health.backlog_records,
            "max_lag_s": health.max_lag_s,
            "max_gap_s": max(health.max_gap_s.values(), default=0.0),
            "failures": health.failures,
        }
    else:
        log.error("%s: AP agent never answered", plan.run_id)
        _wait(scenario, plan)
    report["scenario_ok"] = scenario.returncode == 0
    skew = vm_skew_s()
    report["vm_skew_after_s"] = round(skew, 2)
    if host_slept(time.time() - wall0, time.monotonic() - mono0) or abs(skew) > MAX_VM_SKEW_S:
        log.error("%s: the Mac slept during the run (VM skew %.1f s); re-run it", plan.run_id, skew)
        report |= {"passed": False, "host_slept": True}
    for name in VM_FILES:
        source = f"{VM}:{VM_RUNS}/{plan.run_id}/{name}"
        run(["scp", "-q", source, str(run_dir / name)], check=False, timeout=SSH_TIMEOUT_S)
    (run_dir / "collector.json").write_text(json.dumps(report, indent=1))
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; 0 when every run passed."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("telemetry.collector").setLevel(logging.ERROR)  # one line per run instead

    config = load_batch_config(yaml.safe_load(args.config.read_text()))
    out = ROOT / "data" / "raw" / config.dataset_version
    commit = git_commit()
    results = []
    for plan in plan_runs(config):
        run_dir = out / plan.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        if is_done(run_dir):
            log.info("%s: already done, skipped", plan.run_id)
            report = json.loads((run_dir / "collector.json").read_text())
        else:
            log.info("%s: starting (seed %d, %s)", plan.run_id, plan.seed, plan.split)
            report = play(plan, run_dir, config.agent_wait_s, commit)
        ok = report["passed"] and report["scenario_ok"]
        print(
            f"BATCH_RUN {plan.run_id} split={plan.split} -> {'PASS' if ok else 'FAIL'}", flush=True
        )
        results.append({**report, "scenario": plan.scenario, "seed": plan.seed})
    batch = {
        "dataset_version": config.dataset_version,
        "git_commit": commit,
        "config_hash": inputs_hash(args.config, config.scenarios),
        "runs": results,
    }
    (out / "batch.json").write_text(json.dumps(batch, indent=1))
    passed = sum(r["passed"] and r["scenario_ok"] for r in results)
    verdict = "PASS" if passed == len(results) else "FAIL"
    print(f"BATCH_RESULT runs={passed}/{len(results)} -> {verdict}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
