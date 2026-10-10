"""P5.1: the only way the GenAI layer talks to an LLM (RULEBOOK L-4, ADR-001).

Ollama chat API, structured JSON output at temperature 0, validated by Pydantic (L-2), and
tool-calling turns for the copilot (P5.5): the model names tools, genai/tools runs them.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
V = TypeVar("V")

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
LLM_CONFIG = REPO_ROOT / "config" / "llm.yaml"
CALL_LOG = REPO_ROOT / "logs" / "llm_calls.jsonl"  # gitignored

Message = dict[str, str]
ChatMessage = dict[str, Any]  # Any: tool turns carry tool_calls (lists) besides text
# (path, JSON payload, timeout in seconds) -> parsed JSON reply
Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


class TransportError(Exception):
    """The model could not be reached: connection error, HTTP error or timeout."""


class LLMUnavailableError(Exception):
    """Neither the main nor the fallback model could be reached."""


class LLMOutputError(Exception):
    """The model's reply stayed schema-invalid after every repair attempt (RULEBOOK L-2)."""


@dataclass(frozen=True)
class LLMConfig:
    """Mirrors config/llm.yaml."""

    base_url: str
    model: str
    fallback_model: str
    cloud_timeout_s: float
    timeout_s: float
    temperature: float
    max_repair_retries: int
    keep_alive: str

    @classmethod
    def load(cls, path: Path = LLM_CONFIG) -> LLMConfig:
        """Read config/llm.yaml (unknown keys such as `provider` are ignored)."""
        raw = yaml.safe_load(path.read_text())
        return cls(**{name: raw[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class LLMResult(Generic[V]):
    """A validated reply (model instance or text) and which model produced it."""

    value: V
    model: str
    fell_back: bool


@dataclass(frozen=True)
class ToolCall:
    """One tool the model asked for. Arguments are untrusted: genai/tools validates them (L-6)."""

    name: str
    arguments: dict[str, Any]  # Any: JSON


@dataclass(frozen=True)
class ToolTurn:
    """A tool-calling reply: tool calls to run, or (none) the final answer in `content`."""

    content: str
    tool_calls: list[ToolCall]


@dataclass(frozen=True)
class _Route:
    """Which model a request is on, and the per-call facts every log line repeats."""

    model: str
    fell_back: bool
    timeout_s: float
    prompt_version: str
    schema: str


@dataclass(frozen=True)
class _Reply:
    content: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_s: float
    tool_calls: tuple[ToolCall, ...] = ()


class LLMClient:
    """Calls the main (cloud) model, falling back to the local model (ADR-001).

    Only an unreachable model (connection error, HTTP error, timeout) triggers the fallback. A
    schema-invalid reply is repaired on the same model, at most `max_repair_retries` times, then
    the request fails with LLMOutputError (RULEBOOK L-2). Every call is logged (L-5).
    """

    def __init__(self, config: LLMConfig, *, transport: Transport, log_path: Path) -> None:
        self._config = config
        self._transport = transport
        self._log_path = log_path

    @classmethod
    def from_config(cls, path: Path = LLM_CONFIG, log_path: Path = CALL_LOG) -> LLMClient:
        """The client the rest of the system uses: config/llm.yaml over the local Ollama API."""
        config = LLMConfig.load(path)
        return cls(config, transport=ollama_transport(config.base_url), log_path=log_path)

    @property
    def config(self) -> LLMConfig:
        return self._config

    def complete_json(
        self, messages: Sequence[Message], schema: type[T], *, prompt_version: str
    ) -> LLMResult[T]:
        """Ask for JSON matching `schema`; return the validated instance."""
        fmt = schema.model_json_schema()
        conversation = list(messages)
        route, reply = self._first_reply(conversation, fmt, prompt_version, schema.__name__)
        attempts = 1 + self._config.max_repair_retries
        attempt = 1
        while True:
            try:
                value = schema.model_validate_json(reply.content)
            except ValidationError as exc:
                self._log(route, attempt, reply, error=f"{exc.error_count()} validation error(s)")
                if attempt == attempts:
                    raise LLMOutputError(
                        f"{route.model} reply still invalid after {attempts} attempts: {exc}"
                    ) from exc
                conversation += [
                    {"role": "assistant", "content": reply.content},
                    {"role": "user", "content": _repair_prompt(exc)},
                ]
                attempt += 1
                reply = self._send_or_unavailable(route, conversation, fmt, attempt=attempt)
            else:
                self._log(route, attempt, reply, error="")
                return LLMResult(value=value, model=route.model, fell_back=route.fell_back)

    def complete_text(self, messages: Sequence[Message], *, prompt_version: str) -> LLMResult[str]:
        """Ask for a free-text reply (explanations, chat). Same fallback and logging."""
        route, reply = self._first_reply(list(messages), None, prompt_version, "text")
        self._log(route, 1, reply, error="")
        return LLMResult(value=reply.content, model=route.model, fell_back=route.fell_back)

    def complete_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
        *,
        prompt_version: str,
    ) -> LLMResult[ToolTurn]:
        """One tool-calling turn: the tool calls the model asks for, or its final answer."""
        route, reply = self._first_reply(list(messages), None, prompt_version, "tools", tools)
        self._log(route, 1, reply, error="")
        turn = ToolTurn(reply.content, list(reply.tool_calls))
        return LLMResult(value=turn, model=route.model, fell_back=route.fell_back)

    def _first_reply(
        self,
        conversation: Sequence[ChatMessage],
        fmt: dict[str, Any] | None,
        prompt_version: str,
        schema: str,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> tuple[_Route, _Reply]:
        """Main model first; on a transport failure, the fallback model once (ADR-001)."""
        cfg = self._config
        route = _Route(cfg.model, False, cfg.cloud_timeout_s, prompt_version, schema)
        try:
            return route, self._send(route, conversation, fmt, attempt=1, tools=tools)
        except TransportError:
            route = _Route(cfg.fallback_model, True, cfg.timeout_s, prompt_version, schema)
            return route, self._send_or_unavailable(
                route, conversation, fmt, attempt=1, tools=tools
            )

    def _send_or_unavailable(
        self,
        route: _Route,
        conversation: Sequence[ChatMessage],
        fmt: dict[str, Any] | None,
        *,
        attempt: int,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> _Reply:
        try:
            return self._send(route, conversation, fmt, attempt=attempt, tools=tools)
        except TransportError as exc:
            raise LLMUnavailableError(f"{route.model} unreachable: {exc}") from exc

    def _send(
        self,
        route: _Route,
        conversation: Sequence[ChatMessage],
        fmt: dict[str, Any] | None,
        *,
        attempt: int,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> _Reply:
        payload: dict[str, Any] = {
            "model": route.model,
            "messages": list(conversation),
            "stream": False,
            "options": {"temperature": self._config.temperature},
            "keep_alive": self._config.keep_alive,
        }
        if fmt is not None:
            payload["format"] = fmt
        if tools is not None:
            payload["tools"] = list(tools)
        start = time.monotonic()
        try:
            raw = self._transport("/api/chat", payload, route.timeout_s)
        except TransportError as exc:
            self._log(route, attempt, _Reply("", None, None, time.monotonic() - start), str(exc))
            raise
        message = raw["message"]
        return _Reply(
            content=message.get("content") or "",
            prompt_tokens=raw.get("prompt_eval_count"),
            completion_tokens=raw.get("eval_count"),
            latency_s=time.monotonic() - start,
            tool_calls=tuple(_tool_call(c) for c in message.get("tool_calls") or []),
        )

    def _log(self, route: _Route, attempt: int, reply: _Reply, error: str) -> None:
        """One JSON line per model call. Sizes only: prompt and reply text are never logged."""
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "model": route.model,
            "fallback": route.fell_back,
            "prompt_version": route.prompt_version,
            "schema": route.schema,
            "attempt": attempt,
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
            "latency_s": round(reply.latency_s, 3),
            "valid": not error,
            "error": error,
            "cost_usd": 0.0,  # Ollama (cloud and local) has no per-call charge
        }
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        log.info("llm call %s", entry)


def _tool_call(raw: dict[str, Any]) -> ToolCall:
    """Ollama's tool call; arguments that are a JSON string (some models) are decoded, and
    unreadable ones kept as {"unparsed": text} for the tool layer to refuse."""
    function = raw["function"]
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            arguments = {"unparsed": arguments}
    if not isinstance(arguments, dict):
        arguments = {"unparsed": arguments}
    return ToolCall(str(function["name"]), arguments)


def _repair_prompt(exc: ValidationError) -> str:
    errors = "\n".join(
        f"- {'.'.join(str(part) for part in err['loc']) or '(root)'}: {err['msg']}"
        for err in exc.errors()
    )
    return f"Your JSON did not match the schema:\n{errors}\nReply with corrected JSON only."


def ollama_transport(base_url: str) -> Transport:
    """POST JSON to the Ollama HTTP API. Any failure to get a JSON reply is a TransportError."""

    def post(path: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        request = urllib.request.Request(  # noqa: S310 - base_url comes from config/llm.yaml
            base_url + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as resp:  # noqa: S310 - as above
                body = resp.read()
        except urllib.error.HTTPError as exc:
            raise TransportError(f"HTTP {exc.code}: {exc.reason}") from exc
        except OSError as exc:  # URLError and TimeoutError are both OSErrors
            raise TransportError(str(exc)) from exc
        try:
            reply: dict[str, Any] = json.loads(body)
        except ValueError as exc:
            raise TransportError(f"reply is not JSON: {body[:80]!r}") from exc
        return reply

    return post
