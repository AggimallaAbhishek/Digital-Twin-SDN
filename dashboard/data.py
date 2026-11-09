"""The dashboard's reads: settings, the demo clock and one read of the API per refresh."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st
import yaml

from dashboard.client import ApiClient, ApiError
from dashboard.panels import (
    DemoClock,
    Live,
    demo_clock,
    load_stories,
)

ROOT = Path(__file__).resolve().parents[1]
API_URL = os.getenv("DASHBOARD_API_URL", "http://127.0.0.1:8000")
OPERATOR = os.getenv("OPERATOR_NAME", "operator")
RUN_FILE = ROOT / "logs" / "demo" / "run.json"  # written by `make demo` (experiments/demo.py)
REFRESH = "5s"  # the live panels
CHART_REFRESH = "15s"  # the Altair charts: up to 9 series queries a refresh
READ_TTL_S = 3  # the panels of one refresh share one read of /topology, /actions, /alerts
MAX_LOOKBACK_S = 3600  # the longest window GET /metrics allows
ALERTS_S = 600  # alerts this recent make the episodes
LLM_INTENT_SOURCE = "llm.intent"  # common/schemas.py ActionSource of the intent engine
WINDOW_S = 300  # the charts' window ("last 5 minutes")
RCA_WINDOW_MIN = 5  # genai/rca/evidence.py WINDOW_S: the evidence before an alert, in minutes
SHOWN_CHATS = 2  # copilot exchanges on the Overview card (all of them on the AI copilot page)
CLASSES = {"video": "#7B4FC4", "web": "#C23B7A", "bulk": "#4F6B12"}  # traffic classes (charts)


# ---------------------------------------------------------------- reads


def client() -> ApiClient:
    """The API client; the operator token stays in this server process. Built per use, never
    cached: Streamlit reloads a changed dashboard module, and a cached client from the old
    module raises the old ApiError class, which no `except ApiError` here would catch."""
    return ApiClient(API_URL, os.getenv("OPERATOR_TOKEN") or None)


def config(name: str) -> Any:  # Any: parsed YAML
    """A file of config/, parsed (static settings, read once through the cached callers)."""
    return yaml.safe_load((ROOT / "config" / name).read_text())


@st.cache_data
def campus() -> list[dict[str, Any]]:
    """The zone rectangles from the campus layout file (static layout, not live state)."""
    return [
        {
            "zone": n.replace("_", " "),
            "x": z["x"][0],
            "x2": z["x"][1],
            "y": z["y"][0],
            "y2": z["y"][1],
        }
        for n, z in config("campus_v1.yaml")["zones"].items()
    ]


@st.cache_data
def watch() -> timedelta:
    """How long the executor watches a change after applying it (config/executor.yaml)."""
    return timedelta(seconds=config("executor.yaml")["watch_s"])


def watch_s() -> int:
    """The watch in whole seconds, for the page's words ("watching for 30 s")."""
    return int(watch().total_seconds())


@st.cache_data
def stories() -> dict[str, list[dict[str, Any]]]:
    """The demo stories of the story strip (config/dashboard.yaml)."""
    return load_stories(config("dashboard.yaml"))


@st.cache_data(ttl=READ_TTL_S, show_spinner=False)
def run_file() -> dict[str, Any] | None:
    """The demo playing now (logs/demo/run.json), or None: no demo, or a file being written.
    Read once per refresh for every panel."""
    try:
        run: dict[str, Any] = json.loads(RUN_FILE.read_text())
    except (OSError, ValueError):
        return None
    return run


def demo() -> DemoClock | None:
    """The demo clock now (None without a demo)."""
    return demo_clock(run_file(), now())


def demo_start() -> datetime | None:
    """When the demo started, for event times on the demo clock (None: local time)."""
    clock = demo()
    return clock.start if clock else None


@st.cache_data(ttl=READ_TTL_S, show_spinner=False)
def read_live() -> dict[str, Any]:
    """One read of the API for every panel of a refresh: {"error"} when the API is down;
    topology None before the first telemetry (503); alerts [] when the monitor is off."""
    api = client()
    try:
        actions = api.get("/actions")["actions"]
    except ApiError as exc:
        return {"error": str(exc)}
    try:
        topology = api.get("/topology")
    except ApiError:
        topology = None
    try:
        alerts = api.get(f"/alerts?since={ALERTS_S}")["alerts"]
    except ApiError:
        alerts = []
    return {"topology": topology, "actions": actions, "alerts": alerts}


def live() -> Live | None:
    """This refresh's reads as a Live snapshot; None when the API is not answering."""
    raw = read_live()
    if "error" in raw:
        return None
    return Live(raw["topology"], raw["actions"], raw["alerts"])


def now() -> datetime:
    """Now, in UTC (the API speaks UTC)."""
    return datetime.now(UTC)


@st.cache_data
def ap_names() -> list[str]:
    """The campus's APs (config/campus_v1.yaml), whose load history the story reads."""
    return [str(a["name"]) for a in config("campus_v1.yaml")["aps"]]
