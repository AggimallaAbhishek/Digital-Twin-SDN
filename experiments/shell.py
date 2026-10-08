"""Small subprocess helpers shared by the experiment scripts (batch runner, dataset export)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

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
    """Short commit, marked -dirty when the working tree has changes (RULEBOOK rule 10)."""
    commit = run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, check=True)
    dirty = run(["git", "diff", "--quiet", "HEAD", "--"], check=False).returncode
    return commit.stdout.strip() + ("-dirty" if dirty else "")
