"""P3.6 API (api/app.py): the twin, the verifier, the executor and intents over HTTP."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from api.app import Services, TwinSimulator, create_app
from common.schemas import Action, Policy, Verdict
from controller.executor.executor import Executor, load_executor_config
from controller.executor.ledger import Ledger
from genai.intent.engine import IntentEngine
from genai.llm.client import LLMResult
from twin.radio import RadioParams
from twin.sim.analytical import load_sim_params
from twin.state.builder import CampusAPs
from twin.state.model import APState, FlowState, StationState, TwinState
from twin.verify.verifier import VerifyContext, load_verify_config

ROOT = Path(__file__).resolve().parents[2]
TS = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
TOKEN = "test-operator-token"  # noqa: S105 - a test value, not a secret
CAMPUS = CampusAPs(
    positions={"ap1": (0.0, 0.0), "ap2": (20.0, 0.0)},
    channels={"ap1": 1, "ap2": 6},
    zones={"lab": ((-5.0, 25.0), (-5.0, 5.0))},
)
STATE = TwinState(
    TS,
    {
        "ap1": APState("ap1", (0.0, 0.0), 1, True, 0.9, 14.0),
        "ap2": APState("ap2", (20.0, 0.0), 6, True, 0.1, 14.0),
    },
    {f"sta{i}": StationState(f"sta{i}", (5.0, 0.0), "ap1", "lab") for i in range(1, 7)},
    {f"sta{i}-video": FlowState(f"sta{i}-video", f"sta{i}", "video", 0, 0, 0) for i in range(1, 7)},
)
CONTEXT = VerifyContext(
    CAMPUS,
    RadioParams(4.6, 30.0, 60.0, -16.0, 4.0),
    load_sim_params(yaml.safe_load((ROOT / "config" / "sim.yaml").read_text())),
    load_verify_config(yaml.safe_load((ROOT / "config" / "verify.yaml").read_text())),
)


class FakeActuator:
    def __init__(self) -> None:
        self.applied: list[str] = []

    def apply(self, action: Action, state: TwinState) -> dict[str, Any]:
        self.applied.append(action.action_id)
        return {}

    def revert(self, action: Action, previous: dict[str, Any]) -> None:
        return None


class NoKpis:
    def window(self, start: datetime, end: datetime) -> None:
        return None


class FakeClient:
    def complete_json(self, messages: Any, schema: type[Policy], *, prompt_version: str) -> Any:
        policy = Policy.model_validate(
            {
                "policy_id": "pol_lab_video",
                "intent_text": "x",
                "scope": {"zone": "lab", "app_class": ["video"]},
                "objectives": [{"kpi": "priority", "op": "=", "value": "high"}],
                "created_by": "llm.intent",
            }
        )
        return LLMResult(value=policy, model="fake", fell_back=False)


def _client(
    tmp_path: Path, sim_enabled: bool = True, intents: bool = True, token: str | None = TOKEN
) -> tuple[TestClient, FakeActuator]:
    actuator = FakeActuator()
    config = load_executor_config(yaml.safe_load((ROOT / "config" / "executor.yaml").read_text()))
    executor = Executor(Ledger(tmp_path / "a.db"), actuator, NoKpis(), config, clock=lambda: TS)
    simulator = TwinSimulator(lambda: STATE, CONTEXT)
    services = Services(
        state=lambda: STATE,
        simulator=simulator,
        sim_enabled=sim_enabled,
        executor=executor,
        operator_token=token,
        intents=IntentEngine(FakeClient(), simulator) if intents else None,
        metrics=lambda entity, metric, window_s: [{"ts": "t", "value": 0.5}],
        clock=lambda: TS,
    )
    return TestClient(create_app(services)), actuator


def _action(kind: str, params: dict[str, Any], n: int = 1) -> dict[str, Any]:
    return {
        "action_id": f"act_api_{n}",
        "type": kind,
        "source": "operator",
        "reason": "test",
        "created_at": TS.isoformat(),
        "params": params,
    }


EVERY_TYPE: list[tuple[str, dict[str, Any]]] = [
    ("reroute_flow", {"flow_id": "sta1-video", "path": ["s1", "ap1"]}),
    ("set_qos_queue", {"match": {"zone": "lab"}, "queue_id": 1}),
    ("rate_limit_flow", {"flow_id": "sta1-video", "max_mbps": 2}),
    ("steer_clients", {"from_ap": "ap1", "to_ap": "ap2", "stations": ["sta1"]}),
    ("set_ap_tx_power", {"ap": "ap1", "dbm": 15}),
    ("set_ap_channel", {"ap": "ap1", "channel": 11}),
    ("ap_admin_state", {"ap": "ap2", "state": "down"}),
]


@pytest.mark.parametrize(("kind", "params"), EVERY_TYPE)
def test_every_action_type_gets_a_schema_valid_verdict(
    tmp_path: Path, kind: str, params: dict[str, Any]
) -> None:  # PHASE_PLAN P3.6 Done when
    client, _ = _client(tmp_path)
    response = client.post("/twin/simulate", json={"actions": [_action(kind, params)]})
    assert response.status_code == 200
    [verdict] = [Verdict.model_validate(v) for v in response.json()["verdicts"]]
    assert verdict.action_id == "act_api_1"


def test_a_set_is_verified_together_and_recorded(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    actions = [_action(*EVERY_TYPE[1], n=1), _action(*EVERY_TYPE[3], n=2)]
    verdicts = client.post("/twin/simulate", json={"actions": actions}).json()["verdicts"]
    assert verdicts[0]["predicted"] == verdicts[1]["predicted"]
    history = client.get("/actions").json()["actions"]
    assert [a["action_id"] for a in history] == ["act_api_1", "act_api_2"]


def test_simulation_is_off_until_the_flag_is_on(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, sim_enabled=False)
    response = client.post("/twin/simulate", json={"actions": [_action(*EVERY_TYPE[1])]})
    assert response.status_code == 503
    assert "config/sim.yaml" in response.json()["detail"]


def test_an_invalid_action_is_a_422(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    bad = _action("set_ap_channel", {"ap": "ap1", "channel": 3})
    assert client.post("/twin/simulate", json={"actions": [bad]}).status_code == 422


def test_topology_reflects_the_twin(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    body = client.get("/topology").json()
    assert [a["name"] for a in body["aps"]] == ["ap1", "ap2"]
    assert len(body["stations"]) == 6
    assert body["flows"][0]["flow_id"] == "sta1-video"


def test_metrics_pass_the_query_through(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    body = client.get("/metrics", params={"entity": "ap1", "metric": "channel_util"}).json()
    assert body == {
        "entity": "ap1",
        "metric": "channel_util",
        "window_s": 300,
        "points": [{"ts": "t", "value": 0.5}],
    }


@pytest.mark.parametrize(
    "params", [{"entity": "ap1;drop", "metric": "x"}, {"entity": "ap1", "metric": "x", "window": 0}]
)
def test_bad_metric_queries_are_refused(tmp_path: Path, params: dict[str, Any]) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/metrics", params=params).status_code == 422


def test_an_intent_becomes_verified_recorded_actions(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    body = client.post("/intents", json={"text": "Give video in the lab priority."}).json()
    assert body["error"] == ""
    assert body["policy"]["scope"]["zone"] == "lab"
    [action] = body["actions"]
    assert body["verdicts"][action["action_id"]]["accepted"] is True
    assert client.get("/actions").json()["actions"][0]["action_id"] == action["action_id"]


def test_intents_are_off_until_the_flag_is_on(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, intents=False)
    response = client.post("/intents", json={"text": "Give video in the lab priority."})
    assert response.status_code == 503


def test_approve_and_apply_need_the_operator_token(tmp_path: Path) -> None:
    client, actuator = _client(tmp_path)
    # a channel change is high impact: it always needs an operator (PROJECT_PLAN §8)
    client.post("/twin/simulate", json={"actions": [_action(*EVERY_TYPE[5])]})
    assert client.post("/actions/act_api_1/approve", json={"by": "x"}).status_code == 401
    wrong = {"X-Operator-Token": "nope"}
    assert client.post("/actions/act_api_1/apply", headers=wrong).status_code == 401
    ok = {"X-Operator-Token": TOKEN}
    assert client.post("/actions/act_api_1/apply", headers=ok).status_code == 409  # not approved
    assert (
        client.post("/actions/act_api_1/approve", json={"by": "abhishek"}, headers=ok).status_code
        == 200
    )
    response = client.post("/actions/act_api_1/apply", headers=ok)
    assert response.status_code == 200
    assert actuator.applied == ["act_api_1"]
    statuses = client.get("/actions", params={"status": "applied"}).json()["actions"]
    assert [a["action_id"] for a in statuses] == ["act_api_1"]


def test_without_a_configured_token_nothing_can_be_applied(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, token=None)
    response = client.post("/actions/act_api_1/apply", headers={"X-Operator-Token": ""})
    assert response.status_code == 503
    assert "OPERATOR_TOKEN" in response.json()["detail"]


def test_applying_an_unknown_action_is_a_409(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post("/actions/act_api_9/apply", headers={"X-Operator-Token": TOKEN})
    assert response.status_code == 409
    assert "no verdict" in response.json()["detail"]


def test_the_same_action_id_cannot_be_recorded_twice(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    body = {"actions": [_action(*EVERY_TYPE[1])]}
    assert client.post("/twin/simulate", json=body).status_code == 200
    assert client.post("/twin/simulate", json=body).status_code == 409


def test_approving_an_action_that_needs_no_approval_is_a_409(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.post("/twin/simulate", json={"actions": [_action(*EVERY_TYPE[1])]})  # low impact
    headers = {"X-Operator-Token": TOKEN}
    response = client.post("/actions/act_api_1/approve", json={"by": "x"}, headers=headers)
    assert response.status_code == 409


class TargetOnlyClient(FakeClient):
    def complete_json(self, messages: Any, schema: type[Policy], *, prompt_version: str) -> Any:
        reply = super().complete_json(messages, schema, prompt_version=prompt_version)
        target = [{"kpi": "latency_ms", "op": "<=", "value": 50}]
        return LLMResult(reply.value.model_copy(update={"objectives": target}), "fake", False)


def test_an_intent_with_only_kpi_targets_records_nothing(tmp_path: Path) -> None:
    # an engine whose model answers with a KPI target only: nothing to verify or record
    actuator = FakeActuator()
    config = load_executor_config(yaml.safe_load((ROOT / "config" / "executor.yaml").read_text()))
    executor = Executor(Ledger(tmp_path / "b.db"), actuator, NoKpis(), config, clock=lambda: TS)
    simulator = TwinSimulator(lambda: STATE, CONTEXT)
    services = Services(
        lambda: STATE,
        simulator,
        True,
        executor,
        TOKEN,
        IntentEngine(TargetOnlyClient(), simulator),
        lambda e, m, w: [],
        lambda: TS,
    )
    client = TestClient(create_app(services))
    body = client.post("/intents", json={"text": "Keep lab video latency under 50 ms."}).json()
    assert body["actions"] == []
    assert [o["kpi"] for o in body["standing"]] == ["latency_ms"]
    assert client.get("/actions").json()["actions"] == []


def test_a_metric_the_backend_does_not_know_is_a_422(tmp_path: Path) -> None:
    def unknown(entity: str, metric: str, window_s: int) -> list[dict[str, Any]]:
        raise ValueError(f"unknown metric {metric!r}")

    services = Services(
        lambda: STATE,
        TwinSimulator(lambda: STATE, CONTEXT),
        True,
        Executor(
            Ledger(tmp_path / "c.db"),
            FakeActuator(),
            NoKpis(),
            load_executor_config(yaml.safe_load((ROOT / "config" / "executor.yaml").read_text())),
        ),
        TOKEN,
        None,
        unknown,
        lambda: TS,
    )
    response = TestClient(create_app(services)).get(
        "/metrics", params={"entity": "ap1", "metric": "colour"}
    )
    assert response.status_code == 422
    assert "colour" in response.json()["detail"]
