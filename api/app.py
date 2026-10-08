"""P3.6 REST API (PROJECT_PLAN §7.7): the only module that composes twin, executor and genai.

    app = create_app(services)        # api/main.py builds `services` from config and .env

    GET  /topology                    the twin's current state
    GET  /metrics?entity=&metric=&window=   a telemetry series (seconds of history)
    POST /twin/simulate               {"actions": [Action, ...]} -> joint Verdicts (recorded)
    POST /intents                     {"text": "..."} -> policy, actions, Verdicts (not applied)
    POST /actions/{id}/approve        {"by": "..."}       operator token required
    POST /actions/{id}/apply          the whole verified set the action belongs to; token required
    GET  /actions?status=             the executor's audit log

Feature flags (RULEBOOK B-5): /twin/simulate and /intents answer 503 until config/sim.yaml and
config/intent.yaml are on. Approve and apply need `X-Operator-Token` = OPERATOR_TOKEN
(RULEBOOK §14); with no token configured they are refused. Nothing here applies an action
without the executor's checks (verdict, approval, rate limits, rollback).
"""

from __future__ import annotations

import dataclasses
import hmac
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from common.schemas import Action, Identifier, Verdict
from controller.executor.executor import Executor, ExecutorError
from controller.executor.ledger import ActionRecord
from genai.intent.compiler import FlowRef
from genai.intent.engine import IntentEngine
from twin.state.model import TwinState
from twin.verify.verifier import VerifyContext, verify

Metrics = Callable[[str, str, int], list[dict[str, Any]]]  # Any: JSON points
MAX_WINDOW_S = 3600


class TwinSimulator:
    """Joint verification of an action set on the current twin state (the engine's Simulator)."""

    def __init__(self, state: Callable[[], TwinState], context: VerifyContext) -> None:
        self._state, self._context = state, context

    def verdicts(self, actions: Sequence[Action]) -> list[Verdict]:
        return verify(self._state(), actions, self._context)

    def simulate(self, actions: Sequence[Action]) -> list[dict[str, Any]]:  # Any: JSON
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


class SimulateRequest(BaseModel):
    actions: Annotated[list[Action], Field(min_length=1, max_length=20)]


class IntentRequest(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=1000)]


class ApproveRequest(BaseModel):
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

    def record(actions: Sequence[Action], verdicts: Sequence[Verdict]) -> None:
        try:
            executor.record(actions, verdicts)
        except ExecutorError as exc:
            raise HTTPException(409, str(exc)) from exc

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
        verdicts = services.simulator.verdicts(body.actions)
        record(body.actions, verdicts)
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
            record(result.actions, verdicts)
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
        try:
            executor.approve(action_id, body.by)
        except ExecutorError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"action_id": action_id, "status": "approved"}

    @app.post("/actions/{action_id}/apply")
    def apply(
        action_id: Identifier, x_operator_token: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:  # Any: JSON
        require_operator(x_operator_token)
        try:
            ids = executor.group_of(action_id)
            executor.apply(ids, services.state())
        except ExecutorError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"applied": ids}

    @app.get("/actions")
    def actions(status: str | None = None) -> dict[str, Any]:  # Any: JSON
        return {"actions": [_record_json(r) for r in executor.history(status)]}

    return app


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
    }
