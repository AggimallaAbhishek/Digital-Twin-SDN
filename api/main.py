"""P3.6 wiring: build the API's services from config/*.yaml and the environment.

    make api        # python -m api.main: serves on config/api.yaml's host (localhost) and port

Environment (.env, never printed): INFLUXDB_URL/ORG/TOKEN (and INFLUXDB_BUCKET), OPERATOR_TOKEN.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI

from api.alerts import build_alert_monitor, influx_rows
from api.app import Services, TwinSimulator, create_app
from api.metrics import influx_metrics
from api.wiring import ROOT, build_executor, build_twin, load_yaml
from common.influx import InfluxConnection
from genai.agent.copilot import Copilot, CopilotConfig, load_copilot_config
from genai.intent.engine import IntentEngine, load_intent_config
from genai.llm.client import LLMClient
from genai.tools.http_backend import HttpBackend
from genai.tools.tools import ToolLayer

LOCALHOST = ("127.0.0.1", "localhost", "::1")  # RULEBOOK §14: the API binds to localhost only
MAX_PORT = 65535


@dataclass(frozen=True)
class ApiConfig:
    """config/api.yaml."""

    run_id: str
    ledger: str
    host: str
    port: int
    alerts: bool  # the live anomaly alert monitor (api/alerts.py), B-5 flag


def load_api_config(raw: Mapping[str, Any]) -> ApiConfig:
    """Validate config/api.yaml; ValueError names the bad field."""
    keys = {"run_id", "ledger", "host", "port", "alerts"}
    if set(raw) - keys:
        raise ValueError(f"api config: unknown keys {sorted(set(raw) - keys)}")
    if not isinstance(raw.get("run_id"), str) or not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,64}", raw["run_id"]
    ):
        raise ValueError(f"run_id must be an identifier, got {raw.get('run_id')!r}")
    if not isinstance(raw.get("ledger"), str) or not raw["ledger"]:
        raise ValueError("ledger must be a path")
    if raw.get("host") not in LOCALHOST:
        raise ValueError(f"host must be localhost (RULEBOOK §14), got {raw.get('host')!r}")
    port = raw.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= MAX_PORT:
        raise ValueError(f"port must be 1-65535, got {port!r}")
    if not isinstance(raw.get("alerts"), bool):
        raise ValueError(f"alerts must be true or false, got {raw.get('alerts')!r}")
    return ApiConfig(raw["run_id"], raw["ledger"], raw["host"], port, raw["alerts"])


def build_services() -> Services:
    """Services for the live system. Only the alert monitor's thread queries InfluxDB on its
    own (every 5 s, read-only); everything else waits for a request."""
    api = load_api_config(load_yaml("api.yaml"))
    conn = InfluxConnection.from_env()
    twin = build_twin(conn, api.run_id)
    simulator = TwinSimulator(twin.sync.refresh, twin.context)
    executor = build_executor(conn, api.run_id, ROOT / api.ledger)
    intents = (
        IntentEngine(LLMClient.from_config(), simulator)
        if load_intent_config(load_yaml("intent.yaml")).enabled
        else None
    )

    def clock() -> datetime:
        return datetime.now(UTC)

    copilot = load_copilot_config(load_yaml("copilot.yaml"))
    monitor = build_alert_monitor(influx_rows(conn, api.run_id), clock) if api.alerts else None
    if monitor is not None:  # watches until the process exits (daemon thread)
        threading.Thread(target=monitor.run, args=(threading.Event(),), daemon=True).start()
    return Services(
        state=twin.sync.refresh,
        simulator=simulator,
        sim_enabled=twin.sim.enabled,
        executor=executor,
        operator_token=os.getenv("OPERATOR_TOKEN") or None,
        intents=intents,
        metrics=influx_metrics(conn, api.run_id, clock),
        clock=clock,
        alerts=monitor.recent if monitor is not None else None,
        chat=_chat(copilot) if copilot.enabled else None,
    )


def _chat(config: CopilotConfig) -> Callable[[str], dict[str, Any]]:
    """POST /chat: each question gets a fresh tool session over the API (its own verdicts)."""
    client = LLMClient.from_config()

    def ask(question: str) -> dict[str, Any]:  # Any: JSON
        return Copilot(client, ToolLayer(HttpBackend(config.api_url)), config).ask(question)

    return ask


def app() -> FastAPI:
    """uvicorn factory: `uvicorn api.main:app --factory`."""
    return create_app(build_services())


if __name__ == "__main__":  # make api: serve on config/api.yaml's host and port
    config = load_api_config(load_yaml("api.yaml"))
    uvicorn.run(app(), host=config.host, port=config.port)
