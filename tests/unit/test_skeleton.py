"""P0.3 skeleton checks: every Mac-side package imports, and the layering rules cover them all."""

import importlib
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAC_SIDE_PACKAGES = ["common", "telemetry", "twin", "ml", "genai", "api", "controller.executor"]


@pytest.mark.parametrize("package", MAC_SIDE_PACKAGES)
def test_package_imports(package: str) -> None:
    assert importlib.import_module(package) is not None


def test_every_root_package_has_a_layering_contract() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["tool"]["importlinter"]
    sources = {m for c in config["contracts"] for m in c["source_modules"]}
    assert sources == set(config["root_packages"])


def test_env_example_has_no_values_for_secrets() -> None:
    secret_suffixes = ("_KEY", "_TOKEN", "_PASSWORD")
    for line in (REPO_ROOT / ".env.example").read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip().endswith(secret_suffixes):
            assert value.split("#")[0].strip() == "", f"{name} must be empty in .env.example"
