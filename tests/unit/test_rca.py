"""P5.6 root-cause explainer (genai/rca/): evidence around an alert, then the LLM report."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from genai.llm.client import LLMOutputError, LLMResult
from genai.rca.evidence import gather
from genai.rca.explainer import RCA_DOCS, RCAReport, explain
from genai.tools.mock_backend import MockBackend
from genai.tools.tools import ToolLayer

ALERT_TS = datetime(2026, 10, 9, 12, 5, tzinfo=UTC)
ALERT = {"ts": ALERT_TS.isoformat(), "detector": "isolation_forest", "entity": "ap1", "score": 0.7}


def _series(before: float, after: float, *, stop_at: int = 300) -> list[dict[str, Any]]:
    """One point every 10 s over the 300 s up to the alert; the value changes 60 s before it."""
    return [
        {
            "ts": (ALERT_TS - timedelta(seconds=300 - t)).isoformat(),
            "value": before if t < 240 else after,
        }
        for t in range(0, stop_at, 10)
    ]


SERIES = {  # (entity, metric) -> points
    ("ap1", "channel_util"): _series(0.4, 0.98),
    ("ap1", "n_clients"): _series(3, 8),
    ("ap1", "channel"): _series(1, 1),
    ("ap2", "channel_util"): _series(0.6, 0.6, stop_at=240),
    ("ap2", "n_clients"): _series(5, 5, stop_at=240),
    ("ap2", "channel"): _series(6, 6, stop_at=240),
    ("ap3", "channel_util"): _series(0.2, 0.9),
    ("ap3", "n_clients"): _series(7, 7),
    ("ap3", "channel"): _series(11, 1),
}


class FakeBackend(MockBackend):
    """ap2 stops reporting before the alert, its clients move to ap1; ap3 changes channel."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[tuple[str, str, int]] = []

    def topology(self) -> dict[str, Any]:
        return {
            "aps": [{"name": a, "up": a != "ap2"} for a in ("ap1", "ap2", "ap3")],
            "stations": [
                {"name": "sta4", "ap": None},
                {"name": "sta10", "ap": "ap1"},
                {"name": "sta1", "ap": "ap1"},
            ],
            "flows": [
                {
                    "flow_id": "sta1-video",
                    "latency_ms": 180.0,
                    "loss_pct": 9.0,
                    "throughput_mbps": 0.3,
                },
                {
                    "flow_id": "sta2-web",
                    "latency_ms": 20.0,
                    "loss_pct": 0.0,
                    "throughput_mbps": 0.1,
                },
            ],
        }

    def metrics(self, entity: str, metric: str, window_s: int) -> list[dict[str, Any]]:
        self.asked.append((entity, metric, window_s))
        return SERIES.get((entity, metric), [])

    def recent_actions(self, limit: int) -> list[dict[str, Any]]:
        return [{"action_id": "act_1", "type": "steer_clients", "status": "rolled_back"}]


def test_evidence_shows_what_changed_around_the_alert() -> None:
    backend = FakeBackend()
    evidence = gather(backend, ALERT)
    aps = {a["ap"]: a for a in evidence["aps"]}
    assert aps["ap1"] == {
        "ap": "ap1",
        "up": True,
        "reporting": True,
        "channel_before": 1,
        "channel_now": 1,
        "util_before": 0.4,
        "util_now": 0.98,
        "clients_before": 3,
        "clients_now": 8,
        "stations": ["sta1", "sta10"],  # its stations now, so a steer can name them
    }
    assert aps["ap2"]["up"] is False
    assert aps["ap2"]["reporting"] is False  # no ap_stats in the last 30 s
    assert (aps["ap3"]["channel_before"], aps["ap3"]["channel_now"]) == (11, 1)
    assert evidence["unassociated_stations"] == ["sta4"]
    assert [f["flow_id"] for f in evidence["worst_flows"]] == ["sta1-video", "sta2-web"]
    assert evidence["recent_actions"][0]["status"] == "rolled_back"
    assert evidence["alert"] == ALERT
    assert ("ap1", "channel_util", 300) in backend.asked  # the 5 minutes before the alert


class ScriptedJSON:
    def __init__(self, report: dict[str, Any] | Exception) -> None:
        self.report = report
        self.prompt: list[dict[str, str]] = []

    def complete_json(
        self, messages: Sequence[dict[str, str]], schema: type[RCAReport], *, prompt_version: str
    ) -> LLMResult[RCAReport]:
        self.prompt = list(messages)
        if isinstance(self.report, Exception):
            raise self.report
        return LLMResult(schema.model_validate(self.report), "scripted", fell_back=False)


CAUSE: dict[str, Any] = {
    "cause": "ap2 failed",
    "category": "ap_down",
    "entity": "ap2",
    "evidence": "ap2 stopped reporting; ap1 clients 3 -> 8",
    "confidence": 0.9,
}
REPORT: dict[str, Any] = {
    "summary": "ap2 went down; its stations moved to ap1, which is now overloaded.",
    "likely_causes": [CAUSE],
    "suggested_actions": [
        {
            "type": "steer_clients",
            "params": {"from_ap": "ap1", "to_ap": "ap3", "stations": ["sta1"]},
            "reason": "relieve ap1",
        }
    ],
    "related_docs": ["docs/scenario.md", "docs/nowhere.md"],
}


def test_the_report_comes_with_its_evidence_and_twin_checked_suggestions() -> None:
    backend = FakeBackend()
    llm = ScriptedJSON(REPORT)
    report = explain(llm, backend, ToolLayer(backend), ALERT, clock=lambda: ALERT_TS)
    assert report["summary"] == REPORT["summary"]
    assert report["likely_causes"][0]["category"] == "ap_down"
    [suggested] = report["suggested_actions"]
    assert suggested["action"]["action_id"].startswith("act_rca_")
    assert suggested["verdict"]["accepted"] is True
    assert report["related_docs"] == ["docs/scenario.md"]  # only documents that exist
    assert report["evidence"]["aps"][1]["ap"] == "ap2"
    assert report["model"] == "scripted"
    # the model saw the evidence, not raw telemetry
    assert '"util_now": 0.98' in llm.prompt[-1]["content"]


def test_a_suggestion_the_twin_refuses_is_reported_as_refused() -> None:
    bad = REPORT | {
        "suggested_actions": [
            {"type": "set_ap_channel", "params": {"ap": "ap3", "channel": 3}, "reason": "x"}
        ]
    }
    report = explain(
        ScriptedJSON(bad), FakeBackend(), ToolLayer(FakeBackend()), ALERT, clock=lambda: ALERT_TS
    )
    [suggested] = report["suggested_actions"]
    assert "error" in suggested["verdict"]


def test_no_valid_report_is_an_error_not_a_guess() -> None:
    llm = ScriptedJSON(LLMOutputError("still invalid"))
    with pytest.raises(LLMOutputError):
        explain(llm, FakeBackend(), ToolLayer(FakeBackend()), ALERT, clock=lambda: ALERT_TS)


def test_the_report_schema_bounds_the_model() -> None:
    with pytest.raises(ValueError, match="category"):
        RCAReport.model_validate(REPORT | {"likely_causes": [CAUSE | {"category": "aliens"}]})
    assert "docs/scenario.md" in RCA_DOCS
