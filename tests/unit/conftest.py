"""The small recorded evaluation the paper's evidence, figures and numbers are tested on, built
once per module: `Evidence` is frozen, and the tests derive variants with `dataclasses.replace`.
A module that changes the tree on disk (test_paper_build.py) defines its own, per-test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from experiments import paper_evidence
from tests.unit.test_paper_build import make_tree


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_tree(tmp_path_factory.mktemp("paper"))


@pytest.fixture(scope="module")
def evidence(tree: Path) -> paper_evidence.Evidence:
    return paper_evidence.load_evidence(tree)
