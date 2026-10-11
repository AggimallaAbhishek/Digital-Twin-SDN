"""P6.2 one-command live demo (`make demo`): API + dashboard, then one scenario on the testbed.

    make demo                                   # flash crowd, seed 44 (docs/runbooks/demo.md)
    make demo SCENARIO_DEMO=cochannel_interference   # another scenario
    make demo-stop                              # stop the API and the dashboard

Starts the API (with the V3 loop and the alert monitor, config/api.yaml) and the dashboard in
the background (logs and pids in logs/demo/), waits until both answer, then plays the scenario
on the VM with the collector, tagged with the API's run id so the twin mirrors it live. When the
scenario ends the API and the dashboard keep running for questions; `make demo-stop` ends them.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http import HTTPStatus

from api.main import load_api_config
from api.wiring import ROOT, load_yaml
from experiments.batch import RunPlan
from experiments.run_batch import play
from experiments.shell import git_commit

log = logging.getLogger("experiments.demo")
LOGS = ROOT / "logs" / "demo"
DASHBOARD_PORT = 8501
DASHBOARD_URL = f"http://127.0.0.1:{DASHBOARD_PORT}"
STARTUP_S = 90.0  # the API fits the anomaly detector at start-up (~2 s), Streamlit ~5 s
AGENT_WAIT_S = 180.0
SERVICES = {
    "api": [sys.executable, "-m", "api.main"],
    "dashboard": [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "dashboard/app.py",
        "--server.address=127.0.0.1",
        f"--server.port={DASHBOARD_PORT}",
        "--server.headless=true",
    ],
}


def start(name: str) -> None:
    """Start a service in the background unless it already runs (pid in logs/demo/<name>.pid)."""
    LOGS.mkdir(parents=True, exist_ok=True)
    pid_file = LOGS / f"{name}.pid"
    if pid_file.exists() and _alive(int(pid_file.read_text())):
        log.info("%s already running", name)
        return
    env = os.environ | {"PYTHONPATH": str(ROOT)}
    out = (LOGS / f"{name}.log").open("a")
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        SERVICES[name], cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT
    )
    pid_file.write_text(str(proc.pid))
    log.info("%s started (pid %d, log %s)", name, proc.pid, out.name)


def stop() -> None:
    """Stop every service this script started."""
    for name in SERVICES:
        pid_file = LOGS / f"{name}.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text())
            if _alive(pid):
                os.kill(pid, signal.SIGTERM)
                log.info("%s stopped (pid %d)", name, pid)
            pid_file.unlink()


def wait_for(url: str, timeout_s: float) -> bool:
    """True once `url` answers with HTTP 200 (only http URLs on localhost are polled)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 - local http URL
                if resp.status == HTTPStatus.OK:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    return False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Start the services, wait for them, play the scenario; 0 when the run passed."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", default="lecture_flash_crowd")
    parser.add_argument("--seed", type=int, default=44)
    parser.add_argument("--stop", action="store_true", help="stop the API and the dashboard")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.stop:
        stop()
        return 0
    api = load_api_config(load_yaml("api.yaml"))
    for name in SERVICES:
        start(name)
    api_url = f"http://{api.host}:{api.port}/actions"
    if not wait_for(api_url, STARTUP_S) or not wait_for(DASHBOARD_URL, STARTUP_S):
        log.error("the API or the dashboard did not start; see %s", LOGS)
        return 1
    print(f"DEMO dashboard {DASHBOARD_URL} · API {api_url.rsplit('/', 1)[0]}", flush=True)
    plan = RunPlan(api.run_id, args.scenario, args.seed, "test")
    run_dir = ROOT / "data" / "raw" / "demo" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    report = play(plan, run_dir, AGENT_WAIT_S, git_commit())
    ok = bool(report.get("passed"))
    print(f"DEMO scenario {args.scenario} -> {'PASS' if ok else 'FAIL'} ({run_dir})", flush=True)
    print("DEMO the API and the dashboard keep running; `make demo-stop` ends them", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
