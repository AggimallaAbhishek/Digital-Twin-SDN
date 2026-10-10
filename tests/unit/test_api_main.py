"""P3.6 wiring (api/main.py): the live services build from the repo's config, offline."""

from __future__ import annotations

from typing import Any

import pytest

from api import main
from api.wiring import load_yaml
from genai.agent.copilot import load_copilot_config
from genai.llm.client import LLMClient, LLMResult, ToolTurn


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
    assert services.alerts is None  # config/api.yaml alerts: off until switched on (B-5)
    assert services.chat is None  # config/copilot.yaml: off until M3 (B-5)
    routes = {getattr(r, "path", "") for r in main.app().routes}
    assert {"/topology", "/twin/simulate", "/intents", "/actions/{action_id}/apply"} <= routes


def test_the_api_config_is_validated() -> None:
    config = main.load_api_config(load_yaml("api.yaml"))
    assert (config.host, config.port, config.run_id) == ("127.0.0.1", 8000, "live")
    assert config.alerts is False


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"host": "0.0.0.0"}, "host"),  # noqa: S104 - the value being refused (RULEBOOK §14)
        ({"port": 0}, "port"),
        ({"run_id": "a b"}, "run_id"),
        ({"extra": 1}, "unknown"),
        ({"alerts": "yes"}, "alerts"),
    ],
)
def test_a_bad_api_config_is_refused(change: dict[str, object], named: str) -> None:
    with pytest.raises(ValueError, match=named):
        main.load_api_config(load_yaml("api.yaml") | change)


def test_chat_runs_the_copilot_over_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    class Answers:
        def complete_tools(self, messages: Any, tools: Any, *, prompt_version: str) -> Any:
            return LLMResult(ToolTurn("all quiet", []), "scripted", fell_back=False)

    monkeypatch.setattr(LLMClient, "from_config", Answers)
    config = load_copilot_config(load_yaml("copilot.yaml") | {"enabled": True})
    reply = main._chat(config)("Is anything wrong?")
    assert (reply["answer"], reply["model"]) == ("all quiet", "scripted")
