"""The genai HTTP backend over an in-process API app: the real routes, no socket.

Used by the evaluations (experiments/analysis/rca_eval.py, experiments/genai_actor.py) so the
LLM layer reads and simulates exactly as it does against `make api`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from genai.tools.http_backend import HttpBackend, Send


def inprocess(app: FastAPI) -> tuple[HttpBackend, Send]:
    """An HttpBackend whose requests go straight to `app`, and the raw sender (for routes the
    backend has no method for, such as POST /chat)."""
    client = TestClient(app)

    def send(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        response = client.request(method, path, json=body)
        return response.status_code, response.json()

    return HttpBackend("http://inprocess", send=send), send
