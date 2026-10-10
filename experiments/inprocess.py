"""The genai HTTP backend over an in-process API app: the real routes, no socket.

Used by the evaluations (experiments/analysis/rca_eval.py, experiments/genai_actor.py) so the
LLM layer reads and simulates exactly as it does against `make api`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from genai.tools.http_backend import HttpBackend, Send


def inprocess_send(app: FastAPI) -> Send:
    """(method, path, JSON body) -> (status, JSON reply), straight to `app`."""
    client = TestClient(app)

    def send(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        response = client.request(method, path, json=body)
        return response.status_code, response.json()

    return send


def inprocess_backend(app: FastAPI) -> HttpBackend:
    """HttpBackend whose requests go straight to `app`."""
    return HttpBackend("http://inprocess", send=inprocess_send(app))
