"""P6.2 one-command live demo (`make demo`): API + dashboard, then one scenario on the testbed.

    make demo                                   # flash crowd, seed 44 (docs/runbooks/demo.md)
    make demo SCENARIO_DEMO=cochannel_interference   # another scenario
    make demo-stop                              # stop the API and the dashboard

First stops anything left from an earlier demo, checks the ports are free and moves the old
action ledger to logs/demo/actions-<time>.db (decision P6.2-B). Then starts the API (with the V3
loop and the alert monitor, config/api.yaml) and the dashboard in the background, each in its
own process group (logs and pids in logs/demo/), waits until both answer, then plays the scenario
on the VM with the collector, tagged with the API's run id so the twin mirrors it live. When the
scenario ends the API and the dashboard keep running for questions; `make demo-stop` ends them.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path

from api.app import WORKER_STOP_S
from api.main import REQUEST_DRAIN_S, ApiConfig, load_api_config
from api.wiring import ROOT, load_yaml
from experiments import shell
from experiments.batch import RunPlan
from experiments.run_batch import play
from experiments.shell import git_commit

log = logging.getLogger("experiments.demo")
LOGS = ROOT / "logs" / "demo"
DASHBOARD_PORT = 8501
STARTUP_S = 90.0  # the API fits the anomaly detector at start-up (~2 s), Streamlit ~5 s
# the API's shutdown: open requests (REQUEST_DRAIN_S), then the loop's tick (WORKER_STOP_S),
# plus a margin for the process to exit
EXIT_MARGIN_S = 5.0
STOP_S = REQUEST_DRAIN_S + WORKER_STOP_S + EXIT_MARGIN_S
KILL_WAIT_S = 5.0  # after SIGKILL the group is gone at once, unless only a zombie is left
AGENT_WAIT_S = 180.0


class DemoError(RuntimeError):
    """The demo cannot start; the message says what to do."""


@dataclass(frozen=True)
class Service:
    """A background process of the demo."""

    argv: list[str]
    port: int
    marker: str  # in its command line: a pid from the pid file is still this service
    url: str  # answers 200 once the service is up


def services(api: ApiConfig) -> dict[str, Service]:
    """The API (with the loop and the alert monitor) and the dashboard."""
    return {
        "api": Service(
            [sys.executable, "-m", "api.main"],
            api.port,
            "api.main",
            f"http://{api.host}:{api.port}/actions",
        ),
        "dashboard": Service(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "dashboard/app.py",
                "--server.address=127.0.0.1",
                f"--server.port={DASHBOARD_PORT}",
                "--server.headless=true",
            ],
            DASHBOARD_PORT,
            "streamlit",
            f"http://127.0.0.1:{DASHBOARD_PORT}",
        ),
    }


def port_in_use(port: int) -> bool:
    """True when something on this machine accepts connections on `port`."""
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_ports(demo: Mapping[str, Service]) -> None:
    """DemoError naming any port already taken (often `make api` or `make dashboard`)."""
    for name, service in demo.items():
        if port_in_use(service.port):
            raise DemoError(
                f"port {service.port} ({name}) is in use by another process: stop it"
                " (a `make api` / `make dashboard` terminal?) and run `make demo` again"
            )


def archive_ledger(ledger: Path, stamp: str) -> Path | None:
    """Move the action ledger aside so the demo starts with an empty audit log (decision
    P6.2-B); the old one is kept in logs/demo/. None when there was none."""
    if not ledger.exists():
        return None
    LOGS.mkdir(parents=True, exist_ok=True)
    return ledger.rename(LOGS / f"actions-{stamp}.db")


def start(name: str, service: Service) -> None:
    """Start a service in the background, in its own process group (pid in
    logs/demo/<name>.pid), so stop() reaches everything it starts."""
    LOGS.mkdir(parents=True, exist_ok=True)
    env = os.environ | {"PYTHONPATH": str(ROOT)}
    with (LOGS / f"{name}.log").open("a") as out:  # the child keeps its own handle
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            service.argv,
            cwd=ROOT,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    (LOGS / f"{name}.pid").write_text(str(proc.pid))
    log.info("%s started (pid %d, log %s)", name, proc.pid, out.name)


def stop(demo: Mapping[str, Service]) -> None:
    """Stop the services this script started, and wait until they are gone. A pid that now
    belongs to another process (the file outlived a reboot) is left alone."""
    for name, service in demo.items():
        pid_file = LOGS / f"{name}.pid"
        if not pid_file.exists():
            continue
        pid = int(pid_file.read_text())
        if _running(pid):  # a group with the service's pid as its id (reaps our own child)
            command = _command(pid)
            # '' = the service's first process is gone but what it started is not; a group id
            # is not reused while the group exists, so the group is still ours
            if not command or service.marker in command:
                _terminate(pid)
                log.info("%s stopped (pid %d)", name, pid)
        pid_file.unlink()


def _terminate(pgid: int) -> None:
    """SIGTERM to the process group (the service and all it started), SIGKILL if any of it is
    still there after STOP_S; returns once the group is gone, or KILL_WAIT_S after the
    SIGKILL with a warning (a zombie only its parent, an earlier `make demo`, can reap)."""
    with contextlib.suppress(ProcessLookupError):  # it may end before the signal
        os.killpg(pgid, signal.SIGTERM)
        deadline, killed = time.monotonic() + STOP_S, False
        while _running(pgid):
            if time.monotonic() > deadline:
                if killed:
                    log.warning("process group %d still there after SIGKILL; going on", pgid)
                    return
                os.killpg(pgid, signal.SIGKILL)
                deadline, killed = time.monotonic() + KILL_WAIT_S, True
            time.sleep(0.1)


def _command(pid: int) -> str:
    """The command line of `pid` ('' when there is none)."""
    out = shell.run(["ps", "-o", "command=", "-p", str(pid)], check=False, capture_output=True)
    return out.stdout.strip()


def _running(pgid: int) -> bool:
    """True while any process of the group is alive. A leader that is this process's own
    child (when start() and stop() run in one process, as in the tests) is reaped first, or
    it would linger as a zombie."""
    with contextlib.suppress(ChildProcessError):
        os.waitpid(pgid, os.WNOHANG)
    try:
        os.killpg(pgid, 0)
    except OSError:
        return False
    return True


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


def main(argv: list[str] | None = None) -> int:
    """Start the services, wait for them, play the scenario; 0 when the run passed."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", default="lecture_flash_crowd")
    parser.add_argument("--seed", type=int, default=44)
    parser.add_argument("--stop", action="store_true", help="stop the API and the dashboard")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    api = load_api_config(load_yaml("api.yaml"))
    demo = services(api)
    stop(demo)  # anything left from an earlier demo: every demo starts clean
    if args.stop:
        return 0
    try:
        check_ports(demo)
    except DemoError as exc:
        log.error("%s", exc)
        return 1
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")  # names this demo's files
    archived = archive_ledger(ROOT / api.ledger, stamp)
    if archived is not None:
        log.info("the earlier action ledger is kept as %s", archived)
    for name, service in demo.items():
        start(name, service)
    if not all(wait_for(s.url, STARTUP_S) for s in demo.values()):
        log.error("the API or the dashboard did not start; see %s", LOGS)
        return 1
    print(f"DEMO dashboard {demo['dashboard'].url} · API {demo['api'].url}", flush=True)
    plan = RunPlan(api.run_id, args.scenario, args.seed, "test")
    run_dir = ROOT / "data" / "raw" / "demo" / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    report = play(plan, run_dir, AGENT_WAIT_S, git_commit())
    ok = bool(report.get("passed"))
    print(f"DEMO scenario {args.scenario} -> {'PASS' if ok else 'FAIL'} ({run_dir})", flush=True)
    print("DEMO the API and the dashboard keep running; `make demo-stop` ends them", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
