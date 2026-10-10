"""P5.5 copilot: a tool-using LLM agent that answers operator questions from live evidence.

    copilot = Copilot(LLMClient.from_config(), ToolLayer(HttpBackend(api_url)), config)
    copilot.ask("Why is video in the lab slow?")
    # {"answer": ..., "evidence": [{tool, arguments, result}], "suggested_actions": [...], ...}

The model gets four tools: the three P5.2 reads and `simulate_in_twin`. It never gets
`apply_action`: what it proposes is checked in the twin (and recorded in the audit log by the
API) and returned as a suggestion for the operator (decision P5.5-A). For a proposal the model
names only the type, params and reason; the copilot stamps the action id, source and time, so a
small model need not get them right. Every tool argument is validated by the tool layer (L-6);
a refused call goes back to the model as {"error": ...} for it to correct.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from common.schemas import IMPACT
from genai.llm.client import ChatMessage, LLMResult, ToolCall, ToolTurn
from genai.tools.tools import ToolLayer, proposal

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "copilot_v2.md"
PROMPT_VERSION = "copilot_v2"  # v1: channel changes not checked (P5.5 live q3)
READS = ("get_topology", "get_metrics", "get_alerts")
CUT = " ...(cut)"
MIN_TOOL_CHARS = 100
SIMULATE_SPEC = {
    "type": "function",
    "function": {
        "name": "simulate_in_twin",
        "description": "Ask the digital twin whether an action would help. Returns its verdict "
        "(accepted, predicted KPIs). Changes nothing: an operator decides later.",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    # every allow-listed type but reroute_flow: campus_v1 is a tree (deviation #9)
                    "enum": sorted(t for t in IMPACT if t != "reroute_flow"),
                },
                "params": {"type": "object", "description": "the type's parameters"},
                "reason": {"type": "string", "description": "why, in one sentence"},
            },
            "required": ["type", "params", "reason"],
        },
    },
}


@dataclass(frozen=True)
class CopilotConfig:
    """config/copilot.yaml."""

    enabled: bool
    api_url: str
    max_steps: int
    max_tool_chars: int


def load_copilot_config(raw: Mapping[str, Any]) -> CopilotConfig:
    """Validate config/copilot.yaml; ValueError names the bad key."""
    keys = {"enabled", "api_url", "max_steps", "max_tool_chars"}
    if set(raw) - keys:
        raise ValueError(f"copilot config: unknown keys {sorted(set(raw) - keys)}")
    if not isinstance(raw.get("enabled"), bool):
        raise ValueError("enabled must be true or false")
    url = raw.get("api_url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError(f"api_url must be an http(s) URL, got {url!r}")
    for key, low in (("max_steps", 1), ("max_tool_chars", MIN_TOOL_CHARS)):
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < low:
            raise ValueError(f"{key} must be an integer >= {low}, got {value!r}")
    return CopilotConfig(raw["enabled"], url, raw["max_steps"], raw["max_tool_chars"])


class ToolClient(Protocol):
    """What the copilot needs of genai.llm.client.LLMClient."""

    def complete_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        *,
        prompt_version: str,
    ) -> LLMResult[ToolTurn]: ...


class Copilot:
    """One question -> tool calls -> an answer with its evidence."""

    def __init__(
        self,
        client: ToolClient,
        tools: ToolLayer,
        config: CopilotConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client, self._tools, self._config, self._clock = client, tools, config, clock
        self._system = PROMPT.read_text()
        self._specs = [s for s in tools.specs() if s["function"]["name"] in READS]
        self._specs.append(SIMULATE_SPEC)

    def ask(self, question: str) -> dict[str, Any]:  # Any: JSON
        """Answer `question`; LLM errors (unreachable, ...) propagate to the caller."""
        messages: list[ChatMessage] = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": question},
        ]
        evidence: list[dict[str, Any]] = []
        suggested: list[dict[str, Any]] = []
        model = ""
        for _ in range(self._config.max_steps):
            reply = self._client.complete_tools(
                messages, self._specs, prompt_version=PROMPT_VERSION
            )
            model, turn = reply.model, reply.value
            if not turn.tool_calls:
                return _reply(turn.content, evidence, suggested, model)
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content,
                    "tool_calls": [
                        {"function": {"name": c.name, "arguments": c.arguments}}
                        for c in turn.tool_calls
                    ],
                }
            )
            for call in turn.tool_calls:
                result, suggestion = self._run(call)
                if suggestion is not None:
                    suggested.append(suggestion)
                evidence.append({"tool": call.name, "arguments": call.arguments, "result": result})
                messages.append(
                    {"role": "tool", "tool_name": call.name, "content": self._cut(result)}
                )
        answer = f"I could not finish within {self._config.max_steps} steps; the evidence so far:"
        return _reply(answer, evidence, suggested, model)

    def _run(self, call: ToolCall) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """The tool's result, and the suggestion it makes (a proposal the twin judged)."""
        if call.name in READS:
            return self._tools.call(call.name, call.arguments), None
        if call.name != "simulate_in_twin":
            return {"error": f"unknown tool {call.name!r}"}, None
        args = call.arguments
        reason = args.get("reason") or "copilot proposal"
        action = proposal("copilot", args.get("type"), args.get("params"), reason, self._clock())
        verdict = self._tools.call("simulate_in_twin", {"action": action})
        return verdict, None if "error" in verdict else {"action": action, "verdict": verdict}

    def _cut(self, result: dict[str, Any]) -> str:
        """The tool result for the model, cut to max_tool_chars (the evidence keeps it whole)."""
        text = json.dumps(result, default=str)
        limit = self._config.max_tool_chars
        return text if len(text) <= limit else text[:limit] + CUT


def _reply(
    answer: str, evidence: list[dict[str, Any]], suggested: list[dict[str, Any]], model: str
) -> dict[str, Any]:
    return {
        "answer": answer,
        "evidence": evidence,
        "suggested_actions": suggested,
        "model": model,
        "prompt_version": PROMPT_VERSION,
    }
