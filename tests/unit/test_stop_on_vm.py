"""testbed/stop_on_vm.sh: it stops a testbed run still playing on the VM (SIGINT first, SIGKILL
after a wait), and only a testbed run.

Why the script exists: a demo stopped from the Mac mid-way kept its scenario playing on the VM;
it held the AP agent's port, so the next run failed with "Address already in use" and the
dashboard waited for telemetry (live, 2026-11-09).

The stop is run for real against a stand-in process, with a pass-through `sudo`. The stand-in
cannot read "python3 -B -m testbed..." on macOS (its framework Python rewrites argv[0]), so it
is targeted through RUN_PATTERN, and the default pattern is checked on its own against the
command lines seen on the VM, with grep -E (pgrep's regex dialect).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "testbed" / "stop_on_vm.sh"
pytestmark = pytest.mark.skipif(
    not (shutil.which("pkill") and shutil.which("pgrep")), reason="needs pkill and pgrep"
)

STAND_IN = """\
import signal, sys, time
from pathlib import Path
marker = Path(sys.argv[1])
def stop(signum, frame):
    marker.write_text("cleaned up")
    sys.exit(0)
signal.signal(signal.SIGINT, stop if sys.argv[2] == "polite" else signal.SIG_IGN)
Path(sys.argv[1] + ".ready").write_text("")
time.sleep(60)
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """A PATH whose `sudo` just runs the command."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo = bin_dir / "sudo"
    sudo.write_text('#!/bin/sh\nexec "$@"\n')
    sudo.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}


def _start(tmp_path: Path, mood: str) -> tuple[subprocess.Popen[bytes], Path, str]:
    """A stand-in run, its marker file, and a pattern that matches it and nothing else."""
    tag = f"stand-in-{uuid.uuid4().hex}"
    marker = tmp_path / tag
    proc = subprocess.Popen([sys.executable, "-c", STAND_IN, str(marker), mood])  # noqa: S603
    deadline = time.monotonic() + 10
    while not Path(f"{marker}.ready").exists():  # its SIGINT handler is in place
        assert time.monotonic() < deadline, "the stand-in did not start"
        time.sleep(0.05)
    return proc, marker, f"[s]{tag[1:]}"  # bracketed, like the real one


def _stop(env: dict[str, str], pattern: str, wait_s: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the repo's own script
        [str(SCRIPT)],
        env={**env, "STOP_WAIT_S": str(wait_s), "RUN_PATTERN": pattern},
        capture_output=True,
        text=True,
        timeout=wait_s + 20,
        check=False,
    )


def test_a_run_still_playing_is_asked_to_stop_and_cleans_up(
    env: dict[str, str], tmp_path: Path
) -> None:
    proc, marker, pattern = _start(tmp_path, "polite")
    result = _stop(env, pattern, wait_s=10)
    assert result.returncode == 0, result.stderr
    assert proc.wait(timeout=5) == 0  # ended by its own handler: SIGINT, not SIGKILL
    assert marker.read_text() == "cleaned up"


def test_a_run_that_ignores_the_request_is_killed_after_the_wait(
    env: dict[str, str], tmp_path: Path
) -> None:
    proc, _, pattern = _start(tmp_path, "stubborn")
    result = _stop(env, pattern, wait_s=1)
    assert result.returncode == 0, result.stderr
    assert proc.wait(timeout=5) == -9  # SIGKILL


def test_nothing_running_is_not_an_error(env: dict[str, str]) -> None:
    result = _stop(env, f"[n]othing-{uuid.uuid4().hex}", wait_s=1)
    assert result.returncode == 0, result.stderr


def test_a_failed_signal_is_reported_not_taken_for_nothing_running(
    env: dict[str, str], tmp_path: Path
) -> None:
    sudo = Path(env["PATH"].split(":", 1)[0]) / "sudo"
    sudo.write_text("#!/bin/sh\nexit 3\n")  # e.g. sudo refused
    result = _stop(env, "[a]nything", wait_s=1)
    assert result.returncode == 2
    assert "could not signal" in result.stderr


def _default_pattern() -> str:
    found = re.search(r'RUN_PATTERN="\$\{RUN_PATTERN:-(.+?)\}"', SCRIPT.read_text())
    assert found is not None, "the script's default pattern"
    return found.group(1)


@pytest.mark.parametrize(
    ("command_line", "is_a_run"),
    [  # command lines as `pgrep -af run_scenario` showed them on the VM (2026-11-09)
        ("python3 -B -m testbed.run_scenario experiments/scenarios/x.yaml --run-id live", True),
        ("python3 -B -m testbed.topologies.campus_v1 --check", True),
        ("sudo LOG_DIR=/home/a/p02 timeout 1200 python3 -B -m testbed.run_scenario x", False),
        ("timeout 1200 python3 -B -m testbed.run_scenario x", False),
        (
            "/bin/bash /home/a/Digital-Twin-SDN/testbed/run_on_vm.sh live testbed.run_scenario x",
            False,
        ),
        ("bash -c sudo pkill -INT -f '^python3 -B -m [t]estbed[.]'", False),
        ("python3 -m streamlit run dashboard/app.py", False),
    ],
)
def test_only_the_runs_own_interpreter_matches(command_line: str, is_a_run: bool) -> None:
    # the wrappers end with it; the script's own line and the pkill line must never match
    grep = subprocess.run(  # noqa: S603 - fixed argv
        ["grep", "-qE", _default_pattern()],  # noqa: S607 - grep is on every PATH
        input=command_line,
        text=True,
        check=False,
    )
    assert (grep.returncode == 0) is is_a_run
