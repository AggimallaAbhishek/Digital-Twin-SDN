"""Small subprocess helpers shared by the experiment scripts (batch runner, dataset export)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]  # the commit recorded is this checkout's, not the cwd's
COMMAND_TIMEOUT_S = 60  # git, make vm-clock, ssh date: all quick (RULEBOOK C-6)


def tool(name: str) -> str:
    """Absolute path of a command-line tool on PATH."""
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"{name} not found on PATH")
    return path


def run(
    argv: list[str], *, check: bool, timeout: float = COMMAND_TIMEOUT_S, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    """Run a fixed tool command (argv built by the caller from config and ids; no shell)."""
    command = [tool(argv[0]), *argv[1:]]
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        command, text=True, check=check, timeout=timeout, **kwargs
    )


def git_commit() -> str:
    """Short commit, marked -dirty when the working tree has changes (RULEBOOK rule 10).
    "unknown" outside a git repository, such as the unpacked submission ZIP: the results are
    still reproducible there, only the commit they record is not. A folder without a `.git` of
    its own is "unknown" too: git would walk up into some parent repository."""
    if shutil.which("git") is None or not (REPO / ".git").exists():
        return "unknown"
    commit = run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, check=False
    )
    if commit.returncode != 0:
        return "unknown"
    dirty = run(["git", "diff", "--quiet", "HEAD", "--"], cwd=REPO, check=False).returncode
    return commit.stdout.strip() + ("-dirty" if dirty else "")
