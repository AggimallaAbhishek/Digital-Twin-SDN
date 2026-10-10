"""The live pipeline's parts, built from config/*.yaml: one place for api/main.py and the
experiment harnesses (validation batch, loop batch, rollback check).

Secrets come from the environment through InfluxConnection.from_env() and are never read here.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from common.influx import InfluxConnection
from controller.executor.actuator import AgentActuator
from controller.executor.executor import Executor, load_executor_config
from controller.executor.ledger import Ledger
from controller.executor.live_kpis import InfluxKpis
from twin.radio import RadioParams, load_radio_params
from twin.sim.analytical import SimParams, load_sim_params
from twin.state.builder import CampusAPs, load_campus_aps
from twin.state.sync import TwinSync, load_sync_config
from twin.verify.verifier import VerifyContext, load_verify_config

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(name: str) -> Any:  # Any: parsed YAML, validated by each config loader
    """config/<name>, parsed."""
    return yaml.safe_load((ROOT / "config" / name).read_text())


@dataclass(frozen=True)
class Twin:
    """The twin of one run: layout, radio, simulator settings, live sync and verifier inputs."""

    campus: CampusAPs
    radio: RadioParams
    sim: SimParams
    sync: TwinSync
    context: VerifyContext


def verify_context() -> VerifyContext:
    """What the verifier needs from config: campus layout, radio model, simulator, rules."""
    campus_raw = load_yaml("campus_v1.yaml")
    return VerifyContext(
        load_campus_aps(campus_raw),
        load_radio_params(campus_raw),
        load_sim_params(load_yaml("sim.yaml")),
        load_verify_config(load_yaml("verify.yaml")),
    )


def build_twin(conn: InfluxConnection, run_id: str) -> Twin:
    """The twin mirroring `run_id`'s telemetry (nothing is queried until sync.refresh())."""
    context = verify_context()
    sync = TwinSync(conn, context.campus, run_id, load_sync_config(load_yaml("twin.yaml")))
    return Twin(context.campus, context.radio, context.sim, sync, context)


def agent_url() -> str:
    """The AP agent's base URL (config/telemetry.yaml: vm_host, agent_port)."""
    raw = load_yaml("telemetry.yaml")
    return f"http://{raw['vm_host']}:{int(raw['agent_port'])}"


def build_executor(
    conn: InfluxConnection, run_id: str, ledger: Path, *, unverified_ok: bool = False
) -> Executor:
    """The executor for `run_id`: AP-agent actuator, live KPIs from InfluxDB, ledger at `ledger`.
    `unverified_ok` is for V2 evaluation runs only (ADR-005)."""
    config = load_executor_config(load_yaml("executor.yaml"))
    if unverified_ok:
        config = dataclasses.replace(config, unverified_ok=True)
    return Executor(Ledger(ledger), AgentActuator(agent_url()), InfluxKpis(conn, run_id), config)
