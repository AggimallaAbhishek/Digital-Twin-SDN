"""P5.2 live backend (genai/tools/http_backend.py) against the real P3.6 app (api/app.py)."""

from __future__ import annotations

import email.message
import io
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from common.schemas import ACTION_ADAPTER
from genai.tools.http_backend import HttpBackend
from genai.tools.tools import ToolLayer
from tests.unit.test_api import ALERT, EVERY_TYPE, _action, _client


def _over(client: TestClient) -> HttpBackend:
    """The backend sending its requests to the in-process app instead of a socket."""

    def send(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        response = client.request(method, path, json=body)
        return response.status_code, response.json()

    return HttpBackend("http://127.0.0.1:8000", send=send)


def test_reads_come_from_the_api(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    backend = _over(client)
    assert [a["name"] for a in backend.topology()["aps"]] == ["ap1", "ap2"]
    assert backend.metrics("ap1", "channel_util", 60) == [{"ts": "t", "value": 0.5}]
    assert backend.alerts(120) == [ALERT | {"since_s": 120}]


def test_simulate_returns_the_twins_verdict_and_records_it(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    action = ACTION_ADAPTER.validate_python(_action(*EVERY_TYPE[3]))
    verdict = _over(client).simulate(action)
    assert verdict.action_id == "act_api_1"
    [record] = client.get("/actions").json()["actions"]  # in the audit log (P5 exit gate)
    assert record["verdict"] == verdict.model_dump(mode="json")


def test_recent_actions_are_the_newest_audit_entries(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    backend = _over(client)
    for n in (1, 2):
        backend.simulate(ACTION_ADAPTER.validate_python(_action(*EVERY_TYPE[3], n=n)))
    [newest] = backend.recent_actions(1)
    assert newest["action_id"] == "act_api_2"
    assert newest["type"] == EVERY_TYPE[3][0]
    assert newest["status"] == "verified"
    assert backend.recent_actions(0) == []


def test_apply_only_proposes(tmp_path: Path) -> None:
    client, actuator = _client(tmp_path)
    tools = ToolLayer(_over(client))
    verdict = tools.call("simulate_in_twin", {"action": _action(*EVERY_TYPE[3])})
    assert verdict["accepted"]
    assert not verdict["needs_approval"]
    result = tools.call("apply_action", {"action_id": "act_api_1"})
    assert result["status"] == "awaiting operator"
    assert actuator.applied == []  # nothing reached the network
    [record] = client.get("/actions").json()["actions"]
    assert record["status"] != "applied"


def test_api_errors_reach_the_model_as_errors(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, sim_enabled=False, alerts=None)
    tools = ToolLayer(_over(client))
    simulated = tools.call("simulate_in_twin", {"action": _action(*EVERY_TYPE[3])})
    assert "503" in simulated["error"]
    assert "config/sim.yaml" in simulated["error"]
    assert "alert monitor is off" in tools.call("get_alerts", {"since_s": 60})["error"]


def test_only_http_urls() -> None:
    with pytest.raises(ValueError, match="http"):
        HttpBackend("file:///etc/passwd")


def test_an_unreachable_api_is_an_error_for_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(request: Any, timeout: float) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", down)
    backend = HttpBackend("http://127.0.0.1:8000")
    assert "unreachable" in ToolLayer(backend).call("get_topology", {})["error"]


def test_http_errors_carry_the_apis_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: Any, timeout: float) -> Any:
        body = io.BytesIO(b'{"detail": "off"}')
        raise urllib.error.HTTPError(request.full_url, 503, "off", email.message.Message(), body)

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    with pytest.raises(ValueError, match=r"\(503\): off"):
        HttpBackend("http://127.0.0.1:8000").topology()


def test_a_request_is_json_to_the_configured_api(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []

    class Response(io.BytesIO):
        status = 200

    def answer(request: Any, timeout: float) -> Any:
        sent.append((request.full_url, request.get_method(), request.data, timeout))
        return Response(b'{"alerts": []}')

    monkeypatch.setattr("urllib.request.urlopen", answer)
    assert HttpBackend("http://127.0.0.1:8000/", timeout_s=3).alerts(60) == []
    assert sent == [("http://127.0.0.1:8000/alerts?since=60", "GET", None, 3)]
