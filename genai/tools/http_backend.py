"""P5.2 live backend: the tool layer over the P3.6 REST API (PROJECT_PLAN §7.7).

    backend = HttpBackend("http://127.0.0.1:8000")    # config/copilot.yaml api_url
    tools = ToolLayer(backend)

Reads map to GET /topology, /metrics, /alerts and /actions; `simulate` to POST /twin/simulate,
which also records the verdict in the executor's audit log (so every LLM action has one). `apply` is
**propose-only** (decision P5.5-A): it never calls the API. The action waits in the audit log
for an operator, who approves and applies it through the API with the operator token, which
the LLM never holds. An API error comes back as ValueError, which the tool layer hands to the
model as {"error": ...}.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from common.schemas import Action, Verdict

# (method, path with query, JSON body or None) -> (HTTP status, parsed JSON body)
Send = Callable[[str, str, dict[str, Any] | None], tuple[int, Any]]  # Any: JSON
HTTP_ERROR = 400


class HttpBackend:
    """Backend (genai/tools/backend.py) over the live API."""

    def __init__(self, base_url: str, timeout_s: float = 10.0, send: Send | None = None) -> None:
        if urllib.parse.urlsplit(base_url).scheme not in ("http", "https"):
            raise ValueError("the API URL must be http(s)")
        self._base, self._timeout = base_url.rstrip("/"), timeout_s
        self._send = send or self._urllib

    def topology(self) -> dict[str, Any]:
        body: dict[str, Any] = self._call("GET", "/topology")
        return body

    def metrics(self, entity: str, metric: str, window_s: int) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"entity": entity, "metric": metric, "window": window_s})
        points: list[dict[str, Any]] = self._call("GET", f"/metrics?{query}")["points"]
        return points

    def alerts(self, since_s: int) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = self._call("GET", f"/alerts?since={since_s}")["alerts"]
        return alerts

    def recent_actions(self, limit: int) -> list[dict[str, Any]]:
        records = self._call("GET", "/actions")["actions"][-limit:] if limit > 0 else []
        keep = ("action_id", "status", "applied_at", "note")
        return [
            {k: r[k] for k in keep} | {"type": r["action"]["type"], "params": r["action"]["params"]}
            for r in records
        ]

    def simulate(self, action: Action) -> Verdict:
        body = {"actions": [action.model_dump(mode="json", by_alias=True)]}
        [verdict] = self._call("POST", "/twin/simulate", body)["verdicts"]
        return Verdict.model_validate(verdict)

    def apply(self, action_id: str) -> dict[str, Any]:
        return {
            "action_id": action_id,
            "status": "awaiting operator",
            "detail": "proposed only: an operator approves and applies it in the dashboard",
        }

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        status, data = self._send(method, path, body)
        if status >= HTTP_ERROR:
            detail = data.get("detail") if isinstance(data, dict) else data
            raise ValueError(
                f"API {method} {path.split('?', maxsplit=1)[0]} failed ({status}): {detail}"
            )
        return data

    def _urllib(self, method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        request = urllib.request.Request(  # noqa: S310 - scheme checked in __init__
            self._base + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:  # noqa: S310 - as above
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"null")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ValueError(f"the API is unreachable: {exc}") from exc
