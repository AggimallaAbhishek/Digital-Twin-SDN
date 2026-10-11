"""P3.6 REST API (PROJECT_PLAN §7.7): the only module that composes twin, executor and genai.

    app = create_app(services)        # api/main.py builds `services` from config and .env

    GET  /topology                    the twin's current state
    GET  /metrics?entity=&metric=&window=   a telemetry series (seconds of history)
    POST /twin/simulate               {"actions": [Action, ...]} -> joint Verdicts (recorded)
    POST /intents                     {"text": "..."} -> policy, actions, Verdicts (not applied)
    POST /actions/{id}/approve        {"by": "..."}       operator token required
    POST /actions/{id}/deny           {"by": "..."}       operator token; never applied after
    POST /actions/{id}/apply          the whole verified set the action belongs to; token required
    GET  /actions?status=             the executor's audit log
    POST /chat                        {"question": "..."} -> copilot answer and evidence (P5.5)
    POST /alerts/explain              {"alert": {...}} -> root-cause report (P5.6)
    GET  /alerts?since=               live anomaly alerts of the last `since` s (api/alerts.py)

Feature flags (RULEBOOK B-5): /twin/simulate, /intents and /chat answer 503 until
config/sim.yaml, config/intent.yaml and config/copilot.yaml are on. Approve and apply need
`X-Operator-Token` = OPERATOR_TOKEN (RULEBOOK §14); with no token configured they are refused.
Nothing here applies an action without the executor's checks (verdict, approval, rate limits,
rollback).
"""

from __future__ import annotations

import dataclasses
import hmac
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field

from common.schemas import Action, Identifier, Verdict
from controller.executor.executor import Executor, ExecutorError
from controller.executor.ledger import ActionRecord
from genai.intent.compiler import FlowRef
from genai.intent.engine import IntentEngine
from genai.llm.client import LLMUnavailableError
from twin.state.builder import NoTelemetryError
from twin.state.model import TwinState
from twin.verify.verifier import VerifyContext, verify_scoped

Metrics = Callable[[str, str, int], list[dict[str, Any]]]  # Any: JSON points
Alerts = Callable[[int], list[dict[str, Any]]]  # Any: JSON alerts of the last n seconds
Chat = Callable[[str], dict[str, Any]]  # Any: the copilot's JSON reply to one question
Explain = Callable[[dict[str, Any]], dict[str, Any]]  # Any: alert JSON -> root-cause report
MAX_WINDOW_S = 3600


class TwinSimulator:
    """Joint verification of an action set on the current twin state (the engine's Simulator)."""

    def __init__(self, state: Callable[[], TwinState], context: VerifyContext) -> None:
        self._state, self._context = state, context

    def verdicts(self, actions: Sequence[Action]) -> list[Verdict]:
        """The joint Verdicts for `actions` on the twin's current state."""
        return self.scoped(actions)[0]

    def scoped(self, actions: Sequence[Action]) -> tuple[list[Verdict], list[str]]:
        """The Verdicts and the flows they compared (recorded so the watch measures those)."""
        return verify_scoped(self._state(), actions, self._context)

    def simulate(self, actions: Sequence[Action]) -> list[dict[str, Any]]:  # Any: JSON
        """The same Verdicts as JSON (the intent engine's Simulator protocol)."""
        return [v.model_dump(mode="json") for v in self.verdicts(actions)]


@dataclass(frozen=True)
class Services:
    """Everything the API calls; injected so tests need no network."""

    state: Callable[[], TwinState]
    simulator: TwinSimulator
    sim_enabled: bool
    executor: Executor
    operator_token: str | None  # from the environment, never logged
    intents: IntentEngine | None  # None while config/intent.yaml is off
    metrics: Metrics
    clock: Callable[[], datetime]
    alerts: Alerts | None = None  # None while the alert monitor is off (flag, or no dataset)
    chat: Chat | None = None  # None while config/copilot.yaml is off
    explain: Explain | None = None  # P5.6 root cause; None while the copilot/LLM layer is off


class SimulateRequest(BaseModel):
    """Body of POST /twin/simulate: one set of actions, verified together."""

    actions: Annotated[list[Action], Field(min_length=1, max_length=20)]


class IntentRequest(BaseModel):
    """Body of POST /intents: the operator's words."""

    text: Annotated[str, Field(min_length=1, max_length=1000)]


class ChatRequest(BaseModel):
    """Body of POST /chat: the operator's question."""

    question: Annotated[str, Field(min_length=1, max_length=1000)]


class AlertBody(BaseModel):
    """One alert as GET /alerts returns it (the window it closes ends at `ts`)."""

    ts: AwareDatetime
    detector: Annotated[str, Field(min_length=1, max_length=64)]
    entity: Annotated[str, Field(pattern=r"^(ap[0-9]+|network)$")]
    score: float | None = None
    details: dict[str, Any] | None = None  # Any: JSON


class ExplainRequest(BaseModel):
    """Body of POST /alerts/explain."""

    alert: AlertBody


class ApproveRequest(BaseModel):
    """Body of POST /actions/{id}/approve: who approves."""

    by: Annotated[str, Field(min_length=1, max_length=64)]


def create_app(services: Services) -> FastAPI:
    """The FastAPI app over `services`."""
    app = FastAPI(title="SDN digital twin API", version="0.1")
    executor = services.executor

    def require_operator(token: str | None) -> None:
        if not services.operator_token:
            raise HTTPException(503, "set OPERATOR_TOKEN to allow approvals and applies")
        if token is None or not hmac.compare_digest(token, services.operator_token):
            raise HTTPException(401, "missing or wrong X-Operator-Token")

    @app.exception_handler(ExecutorError)
    def refused(request: Request, exc: ExecutorError) -> JSONResponse:
        """The executor refused (no verdict, needs approval, rate limit ...): 409 with why."""
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(NoTelemetryError)
    def not_yet(request: Request, exc: NoTelemetryError) -> JSONResponse:
        """Before the run's first telemetry there is no state: 503, try again shortly."""
        detail = "no telemetry yet: start the scenario and the collector (make demo)"
        return JSONResponse(status_code=503, content={"detail": detail})

    @app.get("/topology")
    def topology() -> dict[str, Any]:  # Any: JSON
        state = services.state()
        return {
            "ts": state.ts.isoformat(),
            "aps": [dataclasses.asdict(a) for _, a in sorted(state.aps.items())],
            "stations": [dataclasses.asdict(s) for _, s in sorted(state.stations.items())],
            "flows": [dataclasses.asdict(f) for _, f in sorted(state.flows.items())],
        }

    @app.get("/metrics")
    def metrics(
        entity: Annotated[str, Query(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
        metric: Annotated[str, Query(pattern=r"^[a-z_]{1,64}$")],
        window: Annotated[int, Query(ge=1, le=MAX_WINDOW_S)] = 300,
    ) -> dict[str, Any]:  # Any: JSON
        try:
            points = services.metrics(entity, metric, window)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"entity": entity, "metric": metric, "window_s": window, "points": points}

    @app.post("/twin/simulate")
    def simulate(body: SimulateRequest) -> dict[str, Any]:  # Any: JSON
        if not services.sim_enabled:
            raise HTTPException(503, "the twin simulator is off (config/sim.yaml enabled: false)")
        verdicts, scope = services.simulator.scoped(body.actions)
        executor.record(body.actions, verdicts, scope)
        return {"verdicts": [v.model_dump(mode="json") for v in verdicts]}

    @app.post("/intents")
    def intents(body: IntentRequest) -> dict[str, Any]:  # Any: JSON
        if services.intents is None:
            raise HTTPException(503, "the intent engine is off (config/intent.yaml enabled: false)")
        state = services.state()
        result = services.intents.handle(body.text, _flow_refs(state), services.clock())
        if result.actions:
            verdicts = [
                Verdict.model_validate(result.verdicts[a.action_id]) for a in result.actions
            ]
            executor.record(result.actions, verdicts)
        return {
            "policy": result.policy.model_dump(mode="json", by_alias=True)
            if result.policy
            else None,
            "actions": [a.model_dump(mode="json", by_alias=True) for a in result.actions],
            "verdicts": result.verdicts,
            "standing": [o.model_dump(mode="json") for o in result.standing],
            "model": result.model,
            "error": result.error,
        }

    @app.post("/actions/{action_id}/approve")
    def approve(
        action_id: Identifier,
        body: ApproveRequest,
        x_operator_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:  # Any: JSON
        require_operator(x_operator_token)
        executor.approve(action_id, body.by)
        return {"action_id": action_id, "status": "approved"}

    @app.post("/actions/{action_id}/deny")
    def deny(
        action_id: Identifier,
        body: ApproveRequest,
        x_operator_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:  # Any: JSON
        require_operator(x_operator_token)
        executor.deny(action_id, body.by)
        return {"action_id": action_id, "status": "denied"}

    @app.post("/actions/{action_id}/apply")
    def apply(
        action_id: Identifier, x_operator_token: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:  # Any: JSON
        require_operator(x_operator_token)
        ids = executor.group_of(action_id)
        executor.apply(ids, services.state())
        return {"applied": ids}

    @app.get("/actions")
    def actions(status: str | None = None) -> dict[str, Any]:  # Any: JSON
        return {"actions": [_record_json(r) for r in executor.history(status)]}

    _genai_routes(app, services)
    return app


def _genai_routes(app: FastAPI, services: Services) -> None:
    """The LLM layer's routes and live alerts (P5.5, P5.6): each 503 while its part is off."""

    @app.post("/chat")
    def chat(body: ChatRequest) -> dict[str, Any]:  # Any: JSON
        if services.chat is None:
            raise HTTPException(503, "the copilot is off (config/copilot.yaml enabled: false)")
        try:
            return services.chat(body.question)
        except LLMUnavailableError as exc:
            raise HTTPException(503, f"no language model answered: {exc}") from exc

    @app.post("/alerts/explain")
    def explain(body: ExplainRequest) -> dict[str, Any]:  # Any: JSON
        if services.explain is None:
            raise HTTPException(503, "the root-cause explainer is off (config/copilot.yaml)")
        try:
            return services.explain(body.alert.model_dump(mode="json", exclude_none=True))
        except LLMUnavailableError as exc:
            raise HTTPException(503, f"no language model answered: {exc}") from exc

    @app.get("/alerts")
    def alerts(since: Annotated[int, Query(ge=0, le=MAX_WINDOW_S)] = 300) -> dict[str, Any]:
        if services.alerts is None:
            raise HTTPException(
                503, "the alert monitor is off (config/api.yaml alerts: false, or no data/v1)"
            )
        return {"alerts": services.alerts(since)}


def _flow_refs(state: TwinState) -> list[FlowRef]:
    """The flows the intent compiler can target, with the zone of their station."""
    refs = []
    for f in state.flows.values():
        station = state.stations.get(f.sta)
        refs.append(FlowRef(f.flow_id, f.app_class, station.zone if station else None))
    return refs


def _record_json(r: ActionRecord) -> dict[str, Any]:  # Any: JSON
    return {
        "action_id": r.action_id,
        "group_id": r.group_id,
        "status": r.status,
        "action": r.action.model_dump(mode="json", by_alias=True),
        "verdict": r.verdict.model_dump(mode="json"),
        "approved_by": r.approved_by,
        "applied_at": r.applied_at.isoformat() if r.applied_at else None,
        "note": r.note,
        "measured": r.measured.model_dump(mode="json") if r.measured else None,
        "scope": list(r.scope),
    }
