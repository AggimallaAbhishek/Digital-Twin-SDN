"""Shared pipeline wiring (api/wiring.py): built from the repo's config, offline."""

from __future__ import annotations

from pathlib import Path

from api.wiring import agent_url, build_executor, build_twin, load_yaml
from common.influx import InfluxConnection

CONN = InfluxConnection("http://influx.invalid:8086", "org", "telemetry", "placeholder")


def test_the_agent_url_comes_from_the_telemetry_config() -> None:
    raw = load_yaml("telemetry.yaml")
    assert agent_url() == f"http://{raw['vm_host']}:{raw['agent_port']}"


def test_the_twin_is_built_from_the_campus_and_its_configs() -> None:
    twin = build_twin(CONN, "run-x")
    assert sorted(twin.campus.positions) == ["ap1", "ap2", "ap3", "ap4"]
    assert twin.context.campus is twin.campus
    assert twin.sim.enabled is False  # B-5


def test_only_an_explicit_v2_executor_may_apply_unverified(tmp_path: Path) -> None:
    assert not build_executor(CONN, "run-x", tmp_path / "a.db")._config.unverified_ok
    v2 = build_executor(CONN, "run-x", tmp_path / "b.db", unverified_ok=True)
    assert v2._config.unverified_ok  # ADR-005
