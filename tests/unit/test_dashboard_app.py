"""Smoke test of the Streamlit page (dashboard/app.py): every page renders, with a fake API.

The page's logic is tested in test_dashboard_views / _panels / _svg; this runs the page itself
(Streamlit's AppTest, in-process, no browser, no sockets) so a broken name, import or call in
the Streamlit layer fails here instead of in front of the examiners.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard.app import TABS
from dashboard.client import ApiClient, ApiError
from tests.unit.test_dashboard_views import REPORT, TOPOLOGY, _record

APP = Path(__file__).resolve().parents[2] / "dashboard" / "app.py"


def _ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


class FakeApi:
    """The API's replies for one refresh: a proposal waiting for the operator, an applied
    change with its measurement, a rejected one, a recent alert and a few minutes of metrics."""

    def __init__(self) -> None:
        waiting = _record(1, "pending_approval")
        applied = _record(2, "applied", "steer_clients", applied_at=_ago(60))
        applied["measured"] = {"throughput_mbps": 1.2, "latency_ms": 6.0, "loss_pct": 0.5}
        rejected = _record(3, "rejected")
        for n, record in enumerate((waiting, applied, rejected)):
            record["action"]["created_at"] = _ago(120 - 30 * n)
        self.actions = [waiting, applied, rejected]

    def get(self, path: str) -> Any:  # Any: JSON
        route = path.split("?", 1)[0]
        if route == "/actions":
            return {"actions": self.actions}
        if route == "/topology":
            return TOPOLOGY | {"ts": _ago(1)}
        if route == "/alerts":
            return {"alerts": [{"ts": _ago(30), "entity": "ap1", "score": 0.8}]}
        if route == "/metrics":
            return {"points": [{"ts": _ago(s), "value": 0.5} for s in (240, 180, 120, 60, 0)]}
        raise AssertionError(f"the page asked for an unknown route: GET {path}")

    def post(self, path: str, body: dict[str, Any]) -> Any:  # Any: JSON
        if path == "/alerts/explain":
            return REPORT
        raise AssertionError(f"the page posted without an operator: POST {path}")


@pytest.fixture(autouse=True)
def fresh_cache() -> Iterator[None]:
    """st.cache_data lives for the process: each test starts with the API unread."""
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def _render(tab: str) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.session_state["page"] = tab
    return at.run()


@pytest.mark.parametrize("tab", TABS)
def test_every_page_renders_with_live_data(monkeypatch: pytest.MonkeyPatch, tab: str) -> None:
    api = FakeApi()
    monkeypatch.setattr(ApiClient, "get", lambda self, path: api.get(path))
    monkeypatch.setattr(ApiClient, "post", lambda self, path, body: api.post(path, body))
    at = _render(tab)
    assert not at.exception, [e.value for e in at.exception]
    shown = " ".join(m.value for m in at.markdown)
    assert "Waiting for data from the network" not in shown


@pytest.mark.parametrize("tab", TABS)
def test_every_page_renders_while_the_api_is_down(
    monkeypatch: pytest.MonkeyPatch, tab: str
) -> None:
    def down(self: ApiClient, path: str, body: Any = None) -> Any:  # Any: JSON
        raise ApiError("the API is not answering; start it with `make api`")

    monkeypatch.setattr(ApiClient, "get", down)
    monkeypatch.setattr(ApiClient, "post", down)
    at = _render(tab)
    assert not at.exception, [e.value for e in at.exception]
