"""P5.3 intent engine: operator text -> Policy -> actions -> twin verdicts (PROJECT_PLAN §5.1).

    engine = IntentEngine(LLMClient.from_config(), ToolLayer(backend))
    result = engine.handle("Give video calls in the lab priority.", flows, now)

1. The LLM client turns the text into a `Policy` (prompt genai/prompts/intent_v2.md, JSON schema
   output, validation and at most 2 repairs: RULEBOOK L-2). No valid policy -> stop here, so
   invalid LLM output never reaches the compiler.
2. The deterministic compiler (compiler.py) turns the policy into actions, or refuses it.
3. Each action goes to the twin through the `simulate_in_twin` tool (P5.2). Nothing is applied:
   the executor (P4.4) applies accepted actions, after operator approval where needed (L-1).

`POST /intents` exposes this once the API exists (P3.6, decision P5.3-B).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from common.schemas import Action, Objective, Policy
from genai.intent.compiler import CompileError, FlowRef, compile_policy
from genai.llm.client import LLMOutputError, LLMResult, LLMUnavailableError

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "intent_v2.md"
PROMPT_VERSION = "intent_v2"
MAX_INTENT_CHARS = 1000  # = Policy.intent_text max_length


class PolicyClient(Protocol):
    """What the engine needs from genai/llm/client.py LLMClient."""

    def complete_json(
        self, messages: Sequence[dict[str, str]], schema: type[Policy], *, prompt_version: str
    ) -> LLMResult[Policy]: ...


class Tools(Protocol):
    """What the engine needs from genai/tools/tools.py ToolLayer."""

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...  # Any: JSON


@dataclass(frozen=True)
class IntentResult:
    """What became of one intent. `error` is empty when it compiled and was simulated."""

    policy: Policy | None = None
    actions: list[Action] = field(default_factory=list)
    verdicts: dict[str, dict[str, Any]] = field(default_factory=dict)  # Any: tool JSON
    standing: list[Objective] = field(default_factory=list)
    model: str = ""
    error: str = ""


class IntentEngine:
    """Turns operator intents into twin-verified actions. It never applies anything."""

    def __init__(self, client: PolicyClient, tools: Tools, prompt: Path = PROMPT) -> None:
        self._client, self._tools = client, tools
        self._system = prompt.read_text()

    def handle(self, text: str, flows: Sequence[FlowRef], now: datetime) -> IntentResult:
        """Parse, compile and simulate one intent; problems come back in `error`."""
        if not text.strip() or len(text) > MAX_INTENT_CHARS:
            return IntentResult(error=f"intent must be 1-{MAX_INTENT_CHARS} characters")
        messages = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": text},
        ]
        try:
            reply = self._client.complete_json(messages, Policy, prompt_version=PROMPT_VERSION)
        except (LLMOutputError, LLMUnavailableError) as exc:
            return IntentResult(error=f"no valid policy: {exc}")
        # keep the operator's own words for the audit trail, whatever the model echoed
        policy = reply.value.model_copy(update={"intent_text": text})
        try:
            compiled = compile_policy(policy, flows, now)
        except CompileError as exc:
            return IntentResult(policy=policy, model=reply.model, error=f"not compiled: {exc}")
        verdicts = {
            a.action_id: self._tools.call(
                "simulate_in_twin", {"action": a.model_dump(mode="json", by_alias=True)}
            )
            for a in compiled.actions
        }
        return IntentResult(policy, compiled.actions, verdicts, compiled.standing, reply.model)
