"""P3.6 wiring (api/main.py): the live services build from the repo's config, offline."""

from __future__ import annotations

from typing import Any

import pytest

from api import main
from api.wiring import load_yaml
from genai.agent.copilot import load_copilot_config
from genai.llm.client import LLMClient, LLMResult, ToolTurn

OFF = {  # every B-5 flag off, so building the services starts no thread and loads no model
    "sim.yaml": {"enabled": False},
    "intent.yaml": {"enabled": False},
    "copilot.yaml": {"enabled": False},
    "api.yaml": {"alerts": False, "loop": False},
}


def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "INFLUXDB_URL": "http://influx.invalid:8086",
        "INFLUXDB_ORG": "org",
        "INFLUXDB_TOKEN": "placeholder",
        "OPERATOR_TOKEN": "",
    }.items():
        monkeypatch.setenv(name, value)


def _config(overrides: dict[str, dict[str, Any]]) -> Any:
    def load(name: str) -> Any:
        return load_yaml(name) | overrides.get(name, {})

    return load


def test_the_live_app_builds_with_the_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    for module in ("api.main", "api.wiring"):
        monkeypatch.setattr(f"{module}.load_yaml", _config(OFF))
    services = main.build_services()
    assert services.sim_enabled is False
    assert services.intents is None
    assert services.operator_token is None  # empty -> approvals refused
    assert services.alerts is None
    assert services.chat is None
    assert services.explain is None
    assert services.workers == ()
    routes = {getattr(r, "path", "") for r in main.app().routes}
    assert {"/topology", "/twin/simulate", "/intents", "/actions/{action_id}/apply"} <= routes
    assert "/actions/{action_id}/deny" in routes


def test_the_flags_are_on_for_the_demo() -> None:
    # decision P6.1-B: the GenAI exit gate results are in, so the live features are switched on
    assert load_yaml("sim.yaml")["enabled"] is True
    assert load_yaml("intent.yaml")["enabled"] is True
    assert load_yaml("copilot.yaml")["enabled"] is True
    config = main.load_api_config(load_yaml("api.yaml"))
    assert (config.alerts, config.loop) == (True, True)


def test_the_loop_runs_beside_the_api_when_switched_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    loop_only = OFF | {"api.yaml": {"alerts": False, "loop": True}}
    for module in ("api.main", "api.wiring"):
        monkeypatch.setattr(f"{module}.load_yaml", _config(loop_only))
    # a worker of the app (started and stopped by its lifespan), not a thread of its own
    [worker] = main.build_services().workers
    assert worker.__qualname__ == "Loop.run"  # V3 (config/loop.yaml), on the API's executor


def test_serving_caps_the_wait_for_open_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    # uvicorn waits for open requests before the lifespan stops the loop; a slow /chat must
    # not use up the time `make demo-stop` gives the API (decision P6.1-H)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(main, "app", lambda: "the app")
    monkeypatch.setattr("api.main.uvicorn.run", lambda app, **kw: calls.append({"app": app} | kw))
    main.serve()
    [call] = calls
    assert call == {
        "app": "the app",
        "host": "127.0.0.1",
        "port": 8000,
        "timeout_graceful_shutdown": main.REQUEST_DRAIN_S,
    }


def test_the_api_config_is_validated() -> None:
    config = main.load_api_config(load_yaml("api.yaml"))
    assert (config.host, config.port, config.run_id) == ("127.0.0.1", 8000, "live")


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"host": "0.0.0.0"}, "host"),  # noqa: S104 - the value being refused (RULEBOOK §14)
        ({"port": 0}, "port"),
        ({"run_id": "a b"}, "run_id"),
        ({"extra": 1}, "unknown"),
        ({"alerts": "yes"}, "alerts"),
        ({"loop": "yes"}, "loop"),
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


def test_explain_runs_the_root_cause_explainer_over_the_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Report:
        def complete_json(self, messages: Any, schema: Any, *, prompt_version: str) -> Any:
            report = {
                "summary": "ap2 went down",
                "likely_causes": [
                    {
                        "cause": "ap2 failed",
                        "category": "ap_down",
                        "entity": "ap2",
                        "evidence": "ap2 not reporting",
                        "confidence": 0.9,
                    }
                ],
                "suggested_actions": [],
                "related_docs": [],
            }
            return LLMResult(schema.model_validate(report), "scripted", fell_back=False)

    class Backend:  # what the explainer reads; the real one is HttpBackend over the API
        def topology(self) -> dict[str, Any]:
            return {"aps": [], "stations": [], "flows": []}

        def metrics(self, entity: str, metric: str, window_s: int) -> list[Any]:
            return []

        def recent_actions(self, limit: int) -> list[Any]:
            return []

    monkeypatch.setattr(LLMClient, "from_config", Report)
    monkeypatch.setattr("api.main.HttpBackend", lambda url: Backend())
    config = load_copilot_config(load_yaml("copilot.yaml"))
    alert = {"ts": "2026-10-10T12:00:00+00:00", "detector": "isolation_forest", "entity": "ap2"}
    report = main._explain(config)(alert)
    assert (report["summary"], report["model"]) == ("ap2 went down", "scripted")
