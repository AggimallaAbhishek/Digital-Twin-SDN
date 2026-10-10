"""What the tool layer needs from the rest of the system (P5.2).

Two implementations: `MockBackend` (recorded fixtures, until P3.6) and the HTTP backend over the
FastAPI routes of PROJECT_PLAN §7.7 (P5.2 live, Oct 20). genai talks to the system only this way.
"""

from __future__ import annotations

from typing import Any, Protocol

from common.schemas import Action, Verdict


class Backend(Protocol):
    """Read-only views, the twin sandbox, and applying a verified action."""

    def topology(self) -> dict[str, Any]:
        """APs (channel, power, clients), stations (AP, signal, position), switches, links."""

    def metrics(self, entity: str, metric: str, window_s: int) -> list[dict[str, Any]]:
        """Points `{ts, value}` of `metric` for `entity` over the last `window_s` seconds."""

    def alerts(self, since_s: int) -> list[dict[str, Any]]:
        """Anomaly alerts from the last `since_s` seconds."""

    def recent_actions(self, limit: int) -> list[dict[str, Any]]:
        """The newest `limit` entries of the executor's audit log (not an LLM tool: P5.6 input)."""

    def simulate(self, action: Action) -> Verdict:
        """The twin verifier's verdict for `action` (no side effects)."""

    def apply(self, action_id: str) -> dict[str, Any]:
        """Hand a verified action to the executor; the backend re-checks the verdict itself."""
