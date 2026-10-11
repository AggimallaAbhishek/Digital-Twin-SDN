"""P6.1 dashboard's client for the P3.6 API (PROJECT_PLAN §7.7): HTTP only.

The dashboard runs as a Streamlit server process; the operator token (OPERATOR_TOKEN in .env)
stays in that process and is sent only with approve / deny / apply, never to the browser.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

STEPS = ("approve", "deny", "apply")  # the operator's decisions on a verified action
TIMEOUT_S = 60.0  # the copilot can take tens of seconds (several model turns)


def _detail(exc: urllib.error.HTTPError) -> str:
    """The API's `detail`, or the raw body when it is not JSON (a server error page)."""
    body = exc.read()
    try:
        return str(json.loads(body).get("detail", exc.reason))
    except (ValueError, AttributeError):
        return body.decode(errors="replace").strip() or str(exc.reason)


class ApiError(Exception):
    """The API refused a request or could not be reached; the message says why."""


class ApiClient:
    """GET reads and the operator's POSTs against the API."""

    def __init__(self, base_url: str, token: str | None) -> None:
        if urllib.parse.urlsplit(base_url).scheme not in ("http", "https"):
            raise ValueError("the API URL must be http(s)")
        self._base, self._token = base_url.rstrip("/"), token

    def get(self, path: str) -> Any:  # Any: JSON
        return self._send("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> Any:  # Any: JSON
        """An unprivileged POST (chat, intents, twin simulate)."""
        return self._send("POST", path, body)

    def operator(self, action_id: str, step: str, *, by: str) -> Any:  # Any: JSON
        """Approve, deny or apply an action, with the operator token."""
        if step not in STEPS:
            raise ValueError(f"step must be one of {STEPS}, got {step!r}")
        if not self._token:
            raise ApiError("set OPERATOR_TOKEN in .env to approve, deny or apply actions")
        body = None if step == "apply" else {"by": by}
        path = f"/actions/{urllib.parse.quote(action_id)}/{step}"
        return self._send("POST", path, body, {"X-Operator-Token": self._token})

    def _send(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:  # Any: JSON
        request = urllib.request.Request(  # noqa: S310 - scheme checked in __init__
            self._base + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:  # noqa: S310 - as above
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise ApiError(f"{method} {path.split('?', maxsplit=1)[0]}: {_detail(exc)}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ApiError(f"the API is not answering ({exc}); start it with `make api`") from exc
