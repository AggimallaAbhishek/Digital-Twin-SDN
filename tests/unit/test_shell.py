"""experiments/shell.py: the commit every result file records."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from experiments import shell


def _git(repo: Path, *args: str) -> None:
    command = ["git", "-c", "user.email=t@example.org", "-c", "user.name=t", *args]
    subprocess.run(command, cwd=repo, check=True, capture_output=True)  # noqa: S603 - test repo


def test_outside_a_repository_the_commit_is_unknown_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # live 2026-11-09, found verifying the submission: `make results` run from the unpacked
    # Code_and_Data.zip (a folder with no .git) died on `git rev-parse` (exit 128)
    monkeypatch.setattr(shell, "REPO", tmp_path)
    assert shell.git_commit() == "unknown"


def test_a_clean_tree_gives_the_short_commit_and_a_changed_one_is_marked_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("one")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "first")
    monkeypatch.setattr(shell, "REPO", tmp_path)
    elsewhere = tmp_path.parent  # the commit is the checkout's, wherever the script is run from
    monkeypatch.chdir(elsewhere)
    clean = shell.git_commit()
    assert len(clean) >= 7  # a short hash
    assert clean.isalnum()  # and no -dirty marker
    (tmp_path / "a.txt").write_text("two")
    assert shell.git_commit() == f"{clean}-dirty"


def test_a_project_unpacked_inside_another_repository_does_not_borrow_its_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # git walks up to find a repository: an unpacked ZIP in a folder under ~/work (itself a
    # repo) would record that repo's commit as the project's
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("one")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "first")
    unpacked = tmp_path / "Digital-Twin-SDN"
    unpacked.mkdir()
    monkeypatch.setattr(shell, "REPO", unpacked)
    assert shell.git_commit() == "unknown"
