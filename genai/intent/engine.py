"""P5.3 intent engine: operator text -> Policy -> actions -> twin verdicts (PROJECT_PLAN §5.1).

    engine = IntentEngine(LLMClient.from_config(), simulator)
    result = engine.handle("Give video calls in the lab priority.", flows, now)

1. `parse_intent`: the LLM client turns the text into a `Policy` (prompt genai/prompts/
   intent_v2.md, JSON schema output, validation and at most 2 repairs: RULEBOOK L-2). No valid
   policy -> stop here, so invalid LLM output never reaches the compiler. The intent eval
   (genai/eval/run_intents.py) measures this same function.
2. The deterministic compiler (compiler.py) turns the policy into actions, or refuses it.
3. The actions go to the twin **together** (decision P3.4-B: an intent is all or nothing) through
   a `Simulator`: the API passes the twin's joint verifier; `ToolSimulator` asks the P5.2
   `simulate_in_twin` tool one action at a time (offline / mock use). Nothing is applied: the
   executor (P4.4) applies accepted actions, after operator approval where needed (L-1).

Off by default (config/intent.yaml, RULEBOOK B-5); `POST /intents` arrives with the API (P3.6,
decision P5.3-B), which checks the flag.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from common.schemas import Action, Objective, Policy
from genai.intent.compiler import CompileError, FlowRef, compile_policy
from genai.llm.client import LLMOutputError, LLMResult, LLMUnavailableError

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "intent_v2.md"
PROMPT_VERSION = "intent_v2"
MAX_INTENT_CHARS: int = next(  # the schema's limit, not a copy of it (RULEBOOK C-3)
    m.max_length for m in Policy.model_fields["intent_text"].metadata if hasattr(m, "max_length")
)


@dataclass(frozen=True)
class IntentConfig:
    """config/intent.yaml."""

    enabled: bool


def load_intent_config(raw: Mapping[str, Any]) -> IntentConfig:
    """Validate a parsed config/intent.yaml; ValueError if anything but `enabled: bool`."""
    if set(raw) != {"enabled"} or not isinstance(raw["enabled"], bool):
        raise ValueError(f"intent config must be exactly {{enabled: true|false}}, got {raw!r}")
    return IntentConfig(enabled=raw["enabled"])


class PolicyClient(Protocol):
    """What the engine needs from genai/llm/client.py LLMClient."""

    def complete_json(
        self, messages: Sequence[dict[str, str]], schema: type[Policy], *, prompt_version: str
    ) -> LLMResult[Policy]: ...


class Simulator(Protocol):
    """Verdicts (as JSON) for a set of actions, one per action, in order."""

    def simulate(self, actions: Sequence[Action]) -> list[dict[str, Any]]: ...  # Any: JSON


class Tools(Protocol):
    """What ToolSimulator needs from genai/tools/tools.py ToolLayer."""

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...  # Any: JSON


class ToolSimulator:
    """A Simulator over the P5.2 tool layer: one `simulate_in_twin` call per action (not joint)."""

    def __init__(self, tools: Tools) -> None:
        self._tools = tools

    def simulate(self, actions: Sequence[Action]) -> list[dict[str, Any]]:  # Any: JSON
        """One simulate_in_twin call per action, in order."""
        return [
            self._tools.call(
                "simulate_in_twin", {"action": a.model_dump(mode="json", by_alias=True)}
            )
            for a in actions
        ]


def parse_intent(client: PolicyClient, text: str, system: str) -> LLMResult[Policy]:
    """The validated Policy for `text`, keeping the operator's exact words as `intent_text`.

    ValueError if the text is empty or too long; LLMOutputError / LLMUnavailableError from the
    client if no valid policy came back."""
    if not text.strip() or len(text) > MAX_INTENT_CHARS:
        raise ValueError(f"intent must be 1-{MAX_INTENT_CHARS} characters")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    reply = client.complete_json(messages, Policy, prompt_version=PROMPT_VERSION)
    # the audit trail keeps what the operator typed, whatever the model echoed (validated again)
    policy = Policy.model_validate(reply.value.model_dump(by_alias=True) | {"intent_text": text})
    return LLMResult(value=policy, model=reply.model, fell_back=reply.fell_back)


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

    def __init__(self, client: PolicyClient, simulator: Simulator, prompt: Path = PROMPT) -> None:
        self._client, self._simulator = client, simulator
        self._system = prompt.read_text()

    def handle(self, text: str, flows: Sequence[FlowRef], now: datetime) -> IntentResult:
        """Parse, compile and simulate one intent; problems come back in `error`."""
        try:
            reply = parse_intent(self._client, text, self._system)
        except ValueError as exc:
            return IntentResult(error=str(exc))
        except (LLMOutputError, LLMUnavailableError) as exc:
            return IntentResult(error=f"no valid policy: {exc}")
        policy = reply.value
        try:
            compiled = compile_policy(policy, flows, now)
        except CompileError as exc:
            return IntentResult(policy=policy, model=reply.model, error=f"not compiled: {exc}")
        actions = compiled.actions
        results = self._simulator.simulate(actions) if actions else []
        verdicts = {a.action_id: v for a, v in zip(actions, results, strict=True)}
        return IntentResult(
            policy=policy,
            actions=compiled.actions,
            verdicts=verdicts,
            standing=compiled.standing,
            model=reply.model,
        )
