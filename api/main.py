"""P3.6 wiring: build the API's services from config/*.yaml and the environment.

    make api        # uvicorn api.main:app --factory, on 127.0.0.1 (config/api.yaml)

Environment (.env, never printed): INFLUXDB_URL/ORG/TOKEN (and INFLUXDB_BUCKET), OPERATOR_TOKEN.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI

from api.app import Services, TwinSimulator, create_app
from api.metrics import influx_metrics
from common.influx import InfluxConnection
from controller.executor.actuator import AgentActuator
from controller.executor.executor import Executor, load_executor_config
from controller.executor.ledger import Ledger
from controller.executor.live_kpis import InfluxKpis
from genai.intent.engine import IntentEngine, load_intent_config
from genai.llm.client import LLMClient
from telemetry.collector.collector import load_collector_config
from twin.radio import load_radio_params
from twin.sim.analytical import load_sim_params
from twin.state.builder import load_campus_aps
from twin.state.sync import TwinSync, load_sync_config
from twin.verify.verifier import VerifyContext, load_verify_config

ROOT = Path(__file__).resolve().parents[1]


def _yaml(name: str) -> Any:  # Any: parsed YAML, validated by each loader
    return yaml.safe_load((ROOT / "config" / name).read_text())


def build_services() -> Services:
    """Services for the live system (no network until a request needs it)."""
    api = _yaml("api.yaml")
    campus_raw = _yaml("campus_v1.yaml")
    campus = load_campus_aps(campus_raw)
    sim = load_sim_params(_yaml("sim.yaml"))
    conn = InfluxConnection.from_env()
    sync = TwinSync(conn, campus, api["run_id"], load_sync_config(_yaml("twin.yaml")))
    context = VerifyContext(
        campus, load_radio_params(campus_raw), sim, load_verify_config(_yaml("verify.yaml"))
    )
    simulator = TwinSimulator(sync.refresh, context)
    agent = load_collector_config()
    executor = Executor(
        Ledger(ROOT / api["ledger"]),
        AgentActuator(f"http://{agent.vm_host}:{agent.agent_port}"),
        InfluxKpis(conn, api["run_id"]),
        load_executor_config(_yaml("executor.yaml")),
    )
    intents = (
        IntentEngine(LLMClient.from_config(), simulator)
        if load_intent_config(_yaml("intent.yaml")).enabled
        else None
    )

    def clock() -> datetime:
        return datetime.now(UTC)

    return Services(
        state=sync.refresh,
        simulator=simulator,
        sim_enabled=sim.enabled,
        executor=executor,
        operator_token=os.getenv("OPERATOR_TOKEN") or None,
        intents=intents,
        metrics=influx_metrics(conn, api["run_id"], clock),
        clock=clock,
    )


def app() -> FastAPI:
    """uvicorn factory: `uvicorn api.main:app --factory`."""
    return create_app(build_services())
