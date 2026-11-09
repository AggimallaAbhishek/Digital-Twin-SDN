"""P6.2 `make demo` process handling (experiments/demo.py): start, stop, ports, ledger archive."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from experiments import demo, shell


def _sleeper(port: int = 8000) -> demo.Service:
    # a shell that starts a child: stopping the service must reach the child too
    return demo.Service(["sh", "-c", "sleep 30 & sleep 30"], port, "sleep 30", "http://unused")


@pytest.fixture(autouse=True)
def _logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(demo, "LOGS", tmp_path / "demo")
    monkeypatch.setattr(demo, "STOP_S", 5.0)
    yield
    # a failed assert must not leave real test processes behind: kill what is still recorded
    for pid_file in (tmp_path / "demo").glob("*.pid"):
        with contextlib.suppress(OSError, ValueError):
            os.killpg(int(pid_file.read_text()), signal.SIGKILL)


class Signals:
    """os.killpg stand-in: records the signals; the probe (signal 0) answers from `running`."""

    def __init__(self, running: list[bool]) -> None:
        self.sent: list[int] = []
        self._running = running  # one answer per probe; the last one repeats

    def __call__(self, pgid: int, sig: int) -> None:
        if sig != 0:
            self.sent.append(sig)
        elif not (self._running.pop(0) if len(self._running) > 1 else self._running[0]):
            raise ProcessLookupError(pgid)


@pytest.fixture
def no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stop loop's polling runs without real time passing (fake processes only)."""
    monkeypatch.setattr(time, "sleep", lambda s: None)


def _children(pgid: int) -> list[int]:
    out = shell.run(["pgrep", "-g", str(pgid)], check=False, capture_output=True)
    return [int(p) for p in out.stdout.split()]


def test_stop_ends_the_service_and_everything_it_started(tmp_path: Path) -> None:
    services = {"svc": _sleeper()}
    demo.start("svc", services["svc"])
    pid = int((tmp_path / "demo" / "svc.pid").read_text())
    deadline = time.monotonic() + 5
    while len(_children(pid)) < 2 and time.monotonic() < deadline:  # the shell forks its sleep
        time.sleep(0.05)
    assert len(_children(pid)) >= 2  # the shell and its background sleep share the group
    demo.stop(services)
    assert _children(pid) == []
    assert not (tmp_path / "demo" / "svc.pid").exists()


def _pid_file(tmp_path: Path, pid: int) -> Path:
    (tmp_path / "demo").mkdir(exist_ok=True)
    pid_file = tmp_path / "demo" / "svc.pid"
    pid_file.write_text(str(pid))
    return pid_file


@pytest.mark.usefixtures("no_wait")
def test_a_stale_pid_file_never_signals_another_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signals = Signals(running=[True])
    monkeypatch.setattr(os, "killpg", signals)
    pid_file = _pid_file(tmp_path, os.getpid())  # alive, but pytest, not the service
    demo.stop({"svc": _sleeper()})
    assert signals.sent == []
    assert not pid_file.exists()


@pytest.mark.usefixtures("no_wait")
def test_a_group_whose_leader_is_gone_is_still_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the service's first process exited, what it started still runs: no command line, but
    # the group lives on (a group id is not reused while the group exists)
    signals = Signals(running=[True, True, False])
    monkeypatch.setattr(os, "killpg", signals)
    monkeypatch.setattr(demo, "_command", lambda pid: "")
    pid_file = _pid_file(tmp_path, 4242)
    demo.stop({"svc": _sleeper()})
    assert signals.sent == [signal.SIGTERM]
    assert not pid_file.exists()


@pytest.mark.usefixtures("no_wait")
def test_a_group_that_outlives_sigkill_is_given_up_on_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # e.g. a zombie only its own parent (an earlier `make demo`) can reap
    signals = Signals(running=[True])
    monkeypatch.setattr(os, "killpg", signals)
    monkeypatch.setattr(demo, "STOP_S", 0.0)
    monkeypatch.setattr(demo, "KILL_WAIT_S", 0.0)
    demo._terminate(4242)  # returns: no endless wait
    assert signals.sent == [signal.SIGTERM, signal.SIGKILL]
    assert "still there after SIGKILL" in caplog.text


def test_a_group_that_ends_before_the_signal_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def gone(pgid: int, sig: int) -> None:
        raise ProcessLookupError(pgid)

    monkeypatch.setattr(os, "killpg", gone)
    demo._terminate(4242)  # no exception


def test_a_port_in_use_is_named_before_anything_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    demo_services = {"api": _sleeper(8000), "dashboard": _sleeper(8501)}
    monkeypatch.setattr(demo, "port_in_use", lambda port: port == 8501)
    with pytest.raises(demo.DemoError, match=r"port 8501 \(dashboard\)"):
        demo.check_ports(demo_services)
    monkeypatch.setattr(demo, "port_in_use", lambda port: False)
    demo.check_ports(demo_services)  # all free: no error


def test_the_old_ledger_is_archived_not_deleted(tmp_path: Path) -> None:
    ledger = tmp_path / "actions.db"
    ledger.write_text("rehearsal")
    archived = demo.archive_ledger(ledger, "20261011T093005")
    assert archived == tmp_path / "demo" / "actions-20261011T093005.db"
    assert archived.read_text() == "rehearsal"
    assert not ledger.exists()  # the demo starts with an empty audit log
    assert demo.archive_ledger(ledger, "20261011T093010") is None


STARTED = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)


def test_the_run_file_tells_the_dashboard_what_plays_and_since_when(tmp_path: Path) -> None:
    # dashboard/panels.py demo_clock reads this file: the header's scenario and demo clock
    demo.write_run("lecture_flash_crowd", STARTED)
    run = json.loads((tmp_path / "demo" / "run.json").read_text())
    assert run == {
        "scenario": "lecture_flash_crowd",
        "title": "Lecture flash crowd",
        "started_at": "2026-11-09T08:00:00+00:00",
        "duration_s": 600,  # experiments/scenarios/lecture_flash_crowd.yaml
    }
    demo.finish_run(STARTED + timedelta(seconds=610))
    finished = json.loads((tmp_path / "demo" / "run.json").read_text())
    assert finished == run | {"finished_at": "2026-11-09T08:10:10+00:00"}


def test_finishing_without_a_run_file_does_nothing(tmp_path: Path) -> None:
    demo.finish_run(STARTED)
    assert not (tmp_path / "demo" / "run.json").exists()


def test_stopping_the_demo_removes_its_run_file(tmp_path: Path) -> None:
    demo.write_run("lecture_flash_crowd", STARTED)
    demo.stop({})
    assert not (tmp_path / "demo" / "run.json").exists()  # the dashboard shows no demo clock


def test_a_scenario_left_playing_on_the_vm_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    # live 2026-11-09: `make demo-stop` + `make demo` left the first scenario playing on the VM;
    # it held the AP agent's port, so the next one failed ("Address already in use") and the
    # dashboard waited for telemetry forever
    sent: list[list[str]] = []

    def ssh(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        sent.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(demo, "run", ssh)
    demo.stop_vm_scenario()
    [argv] = sent
    assert (argv[0], argv[-2]) == ("ssh", "sdnvm")
    assert "BatchMode=yes" in argv  # never a password prompt: fail fast
    script = argv[-1]
    assert "pkill -INT" in script  # first a SIGINT: the scenario's own cleanup runs
    assert "pkill -KILL" in script  # then, if it is still there, it is killed
    # the pattern must not match the ssh command that carries it (it would kill itself)
    assert "testbed.run_scenario" not in script


def test_an_unreachable_vm_does_not_stop_the_demo_from_stopping(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def down(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, 45)

    monkeypatch.setattr(demo, "run", down)
    demo.stop_vm_scenario()  # logs, never raises: the Mac side still stops
    assert "could not check the VM" in caplog.text


def test_stopping_a_demo_also_stops_its_scenario_on_the_vm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(demo, "stop", lambda services: calls.append("services"))
    monkeypatch.setattr(demo, "stop_vm_scenario", lambda: calls.append("vm"))
    assert demo.main(["--stop"]) == 0
    assert calls == ["services", "vm"]
