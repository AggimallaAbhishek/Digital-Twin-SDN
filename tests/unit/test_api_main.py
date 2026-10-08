"""P3.6 wiring (api/main.py): the live services build from the repo's config, offline."""

from __future__ import annotations

import pytest

from api import main


def test_the_live_app_builds_with_the_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "INFLUXDB_URL": "http://influx.invalid:8086",
        "INFLUXDB_ORG": "org",
        "INFLUXDB_TOKEN": "placeholder",
        "OPERATOR_TOKEN": "",
    }.items():
        monkeypatch.setenv(name, value)
    services = main.build_services()
    assert services.sim_enabled is False  # config/sim.yaml: off until M2 (B-5)
    assert services.intents is None  # config/intent.yaml: off until M3 (B-5)
    assert services.operator_token is None  # empty -> approvals refused
    routes = {getattr(r, "path", "") for r in main.app().routes}
    assert {"/topology", "/twin/simulate", "/intents", "/actions/{action_id}/apply"} <= routes
