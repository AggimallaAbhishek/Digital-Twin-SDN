"""P5.2 tool layer: the only way the LLM agent reads or changes the network (RULEBOOK L-1).

    tools = ToolLayer(MockBackend())          # HTTP backend once the API exists (P3.6)
    tools.specs()                             # tool definitions for the LLM (Ollama tool format)
    tools.call("simulate_in_twin", {"action": {...}})

Every argument the LLM sends is untrusted (L-6): it is validated with pydantic before use, and a
bad call comes back as `{"error": ...}` for the model to read, never as an exception. Safety:
`apply_action` only applies an action that got an accepted verdict from `simulate_in_twin` in this
session, never twice, and a high-impact one only after `approve()`, which the operator calls
through the API: it is not a tool, so the LLM cannot approve its own actions (T-5a, T-5c).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, Field, ValidationError

from common.schemas import Action, Contract, Verdict
from genai.tools.backend import Backend

ActionId = Annotated[str, Field(pattern=r"^act_[A-Za-z0-9_]+$", max_length=64)]


class NoArgs(Contract):
    """No arguments."""


class MetricsArgs(Contract):
    """Arguments of get_metrics."""

    entity: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=64)] = Field(
        description="AP name (ap1) or flow id (sta1-video)"
    )
    metric: Annotated[str, Field(pattern=r"^[a-z_]+$", max_length=32)] = Field(
        description="e.g. throughput_mbps, latency_ms, loss_pct, channel_util, n_clients"
    )
    window_s: Annotated[int, Field(ge=1, le=3600)] = Field(description="look-back window")


class AlertsArgs(Contract):
    """Arguments of get_alerts."""

    since_s: Annotated[int, Field(ge=0, le=86400)] = Field(description="look-back window")


class SimulateArgs(Contract):
    """Arguments of simulate_in_twin."""

    action: Action = Field(description="one allow-listed action (common/schemas.py)")


class ApplyArgs(Contract):
    """Arguments of apply_action."""

    action_id: ActionId = Field(description="id of an action with an accepted twin verdict")


@dataclass(frozen=True)
class _Tool:
    """One tool: its arguments model, what the LLM is told, and the ToolLayer method behind it."""

    args: type[BaseModel]
    description: str
    method: str


_TOOLS: dict[str, _Tool] = {  # the one registry: order = TOOL_NAMES = what the LLM sees
    "get_topology": _Tool(
        NoArgs, "Current APs (channel, power, clients), stations and switches.", "_topology"
    ),
    "get_metrics": _Tool(
        MetricsArgs, "Recent values of one metric for one AP or traffic flow.", "_get_metrics"
    ),
    "get_alerts": _Tool(AlertsArgs, "Anomaly alerts raised recently.", "_get_alerts"),
    "simulate_in_twin": _Tool(
        SimulateArgs,
        "Ask the digital twin whether an action helps. Returns the verifier's verdict; "
        "changes nothing.",
        "_simulate",
    ),
    "apply_action": _Tool(
        ApplyArgs,
        "Apply an action that simulate_in_twin accepted. High-impact actions also need an "
        "operator's approval first.",
        "_apply",
    ),
}
TOOL_NAMES = tuple(_TOOLS)
_SPECS = [  # built once: the Action union's JSON schema is large
    {
        "type": "function",
        "function": {
            "name": name,
            "description": tool.description,
            "parameters": tool.args.model_json_schema(),
        },
    }
    for name, tool in _TOOLS.items()
]


class ToolLayer:
    """Validated tool calls over a Backend, plus the verdict ledger that guards apply_action."""

    def __init__(self, backend: Backend) -> None:
        self._backend = backend
        self._verdicts: dict[str, Verdict] = {}
        self._approved: set[str] = set()
        self._applied: set[str] = set()

    def specs(self) -> list[dict[str, Any]]:
        """Tool definitions for the LLM, in TOOL_NAMES order."""
        return copy.deepcopy(_SPECS)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one tool call from the LLM; errors come back as {"error": ...}."""
        tool = _TOOLS.get(name)
        if tool is None:
            return {"error": f"unknown tool {name!r}"}
        try:
            args = tool.args.model_validate(arguments)
            result: dict[str, Any] = getattr(self, tool.method)(args)
            return result
        except ValidationError as exc:
            return {"error": f"invalid arguments for {name}: {exc.errors()[0]['msg']}"}
        except ValueError as exc:
            return {"error": str(exc)}

    def approve(self, action_id: str) -> None:
        """Operator approval of a high-impact action (API/dashboard only; not a tool)."""
        if self._accepted(action_id) is None:
            raise ValueError(f"no accepted twin verdict for {action_id}")
        self._approved.add(action_id)

    def _accepted(self, action_id: str) -> Verdict | None:
        """This session's accepted verdict for `action_id`, if there is one."""
        verdict = self._verdicts.get(action_id)
        return verdict if verdict is not None and verdict.accepted else None

    def _topology(self, _: NoArgs) -> dict[str, Any]:
        return self._backend.topology()

    def _get_metrics(self, args: MetricsArgs) -> dict[str, Any]:
        points = self._backend.metrics(args.entity, args.metric, args.window_s)
        return {"entity": args.entity, "metric": args.metric, "points": points}

    def _get_alerts(self, args: AlertsArgs) -> dict[str, Any]:
        return {"alerts": self._backend.alerts(args.since_s)}

    def _simulate(self, args: SimulateArgs) -> dict[str, Any]:
        verdict = self._backend.simulate(args.action)
        self._verdicts[verdict.action_id] = verdict
        return verdict.model_dump(mode="json")

    def _apply(self, args: ApplyArgs) -> dict[str, Any]:
        action_id = args.action_id
        verdict = self._accepted(action_id)
        if verdict is None:
            return {"error": f"refused: no accepted twin verdict for {action_id}"}
        if action_id in self._applied:
            return {"error": f"refused: {action_id} was already applied"}
        if verdict.needs_approval and action_id not in self._approved:
            return {"error": f"refused: {action_id} is high-impact and needs operator approval"}
        result = self._backend.apply(action_id)
        self._applied.add(action_id)
        return result
