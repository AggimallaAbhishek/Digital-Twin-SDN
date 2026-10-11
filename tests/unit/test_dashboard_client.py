"""P6.1 dashboard HTTP client (dashboard/client.py): the API over HTTP, the token server-side."""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
from typing import Any

import pytest

from dashboard.client import ApiClient, ApiError

TOKEN = "test-operator-token"  # noqa: S105 - a test value, not a secret


class Response(io.BytesIO):
    status = 200


def _capture(monkeypatch: pytest.MonkeyPatch, reply: Any) -> list[Any]:
    sent: list[Any] = []

    def answer(request: Any, timeout: float) -> Any:
        sent.append(request)
        return Response(json.dumps(reply).encode())

    monkeypatch.setattr("urllib.request.urlopen", answer)
    return sent


def test_reads_are_plain_gets(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _capture(monkeypatch, {"alerts": []})
    assert ApiClient("http://127.0.0.1:8000", token=TOKEN).get("/alerts?since=300") == {
        "alerts": []
    }
    [request] = sent
    assert (request.full_url, request.get_method()) == (
        "http://127.0.0.1:8000/alerts?since=300",
        "GET",
    )
    assert request.get_header("X-operator-token") is None  # reads never carry the token


def test_operator_actions_carry_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _capture(monkeypatch, {"action_id": "act_1", "status": "approved"})
    client = ApiClient("http://127.0.0.1:8000", token=TOKEN)
    client.operator("act_1", "approve", by="abhishek")
    [request] = sent
    assert request.full_url == "http://127.0.0.1:8000/actions/act_1/approve"
    assert request.get_header("X-operator-token") == TOKEN
    assert json.loads(request.data) == {"by": "abhishek"}


def test_apply_sends_no_body(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _capture(monkeypatch, {"applied": ["act_1"]})
    ApiClient("http://127.0.0.1:8000", token=TOKEN).operator("act_1", "apply", by="abhishek")
    assert sent[0].data is None


def test_only_known_operator_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, {})
    with pytest.raises(ValueError, match="step"):
        ApiClient("http://127.0.0.1:8000", token=TOKEN).operator("act_1", "delete", by="x")


def test_without_a_token_operator_actions_are_refused_before_sending() -> None:
    with pytest.raises(ApiError, match="OPERATOR_TOKEN"):
        ApiClient("http://127.0.0.1:8000", token=None).operator("act_1", "approve", by="x")


def test_api_errors_carry_the_apis_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: Any, timeout: float) -> Any:
        body = io.BytesIO(b'{"detail": "act_1 needs operator approval first"}')
        raise urllib.error.HTTPError(
            request.full_url, 409, "Conflict", email.message.Message(), body
        )

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    with pytest.raises(ApiError, match="needs operator approval first"):
        ApiClient("http://127.0.0.1:8000", token=TOKEN).operator("act_1", "apply", by="x")


def test_a_plain_text_error_is_reported_not_crashed_on(monkeypatch: pytest.MonkeyPatch) -> None:
    # found in the P6.2 demo: a 500 with the body "Internal Server Error" crashed the page
    def plain(request: Any, timeout: float) -> Any:
        body = io.BytesIO(b"Internal Server Error")
        raise urllib.error.HTTPError(request.full_url, 500, "Error", email.message.Message(), body)

    monkeypatch.setattr("urllib.request.urlopen", plain)
    with pytest.raises(ApiError, match="Internal Server Error"):
        ApiClient("http://127.0.0.1:8000", token=TOKEN).get("/topology")


def test_an_unreachable_api_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(request: Any, timeout: float) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", down)
    with pytest.raises(ApiError, match="make api"):
        ApiClient("http://127.0.0.1:8000", token=TOKEN).get("/topology")


def test_only_http_urls() -> None:
    with pytest.raises(ValueError, match="http"):
        ApiClient("file:///etc/passwd", token=None)


def test_chat_and_intents_are_posts_without_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _capture(monkeypatch, {"answer": "ap1 is busy"})
    reply = ApiClient("http://127.0.0.1:8000", token=TOKEN).post("/chat", {"question": "why?"})
    assert reply == {"answer": "ap1 is busy"}
    assert (sent[0].get_method(), json.loads(sent[0].data)) == ("POST", {"question": "why?"})
    assert sent[0].get_header("X-operator-token") is None
