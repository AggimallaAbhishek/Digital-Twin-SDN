"""The end-of-demo run report (experiments/demo_report.py): facts, AI summary, page, rebuild."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from api.main import load_api_config
from api.wiring import load_yaml
from common.schemas import ACTION_ADAPTER, APStats, KPIRecord, TelemetryRecord, Verdict
from controller.executor.ledger import Ledger
from experiments import demo_report
from genai.llm.client import LLMResult, LLMUnavailableError

T0 = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)  # the "started" event of the run


def _at(t_s: float) -> datetime:
    return T0 + timedelta(seconds=t_s)


def _lines(*events: dict[str, Any]) -> str:
    return "".join(json.dumps(e) + "\n" for e in events)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """A demo run folder as play() leaves it (lecture flash crowd, seed 44)."""
    run = tmp_path / "20261109T075955"
    run.mkdir()
    manifest = {
        "scenario_id": "lecture_flash_crowd",
        "run_id": "live",
        "seed": 44,
        "duration_s": 600.0,
        "git_commit": "f8c2468",
        "started_at": "2026-11-09T07:59:58+00:00",
    }
    (run / "manifest.json").write_text(json.dumps(manifest))
    collector = {"passed": True, "scenario_ok": True, "records": 125488, "max_lag_s": 1.19}
    (run / "collector.json").write_text(json.dumps(collector | {"max_gap_s": 1.0}))
    by_class = {
        "video": {
            "throughput_mbps": 0.357,
            "latency_ms_p50": 7.9,
            "latency_ms_p95": 23.1,
            "loss_pct": 10.7,
        },
        "web": {
            "throughput_mbps": 2.714,
            "latency_ms_p50": 4.05,
            "latency_ms_p95": 20.4,
            "loss_pct": 2.24,
        },
    }
    (run / "summary.json").write_text(json.dumps({"by_class": by_class}))
    old = {"t_s": 0.0, "kind": "started", "utc": "2026-10-10T16:15:35+00:00"}
    (run / "events.jsonl").write_text(
        _lines(
            old,  # an earlier run in the same file (the VM appended before 2026-11-09)
            {"t_s": 300.0, "kind": "ap_down", "ap": "ap9"},
            {
                "t_s": 0.0,
                "kind": "started",
                "utc": T0.isoformat(),
                "associated": 20,
                "stations": 20,
            },
            {"t_s": 0.01, "kind": "interference_cap", "ap": "ap1", "cap_mbps": 3.45},
            {"t_s": 0.03, "kind": "interference_cap", "ap": "ap4", "cap_mbps": 3.45},
            {"t_s": 151.2, "kind": "arrived", "sta": "sta2", "ap": "ap1", "associated": True},
            {"t_s": 153.9, "kind": "arrived", "sta": "sta3", "ap": "ap1", "associated": True},
            {"t_s": 158.0, "kind": "arrived", "sta": "sta5", "ap": "ap1", "associated": False},
            {
                "t_s": 210.57,
                "kind": "traffic_started",
                "flows": ["sta1-video", "sta2-video", "sta3-web"],
            },
            {"t_s": 600.0, "kind": "finished"},
        )
    )
    return run


STEER = {
    "action_id": "act_20261109_080016_001_1978d41e",
    "source": "optimizer.heuristic",
    "reason": "ap1 at 100% of capacity (>= 80%); ap3 at 10% <b>",
    "created_at": "2026-11-09T08:04:16.680000Z",
    "type": "steer_clients",
    "params": {"from_ap": "ap1", "to_ap": "ap3", "stations": ["sta2", "sta12"]},
}
KPIS = {"throughput_mbps": 0.53, "latency_ms": 12.9, "loss_pct": 27.3, "jain": 0.51}


def _verdict(action_id: str, accepted: bool) -> Verdict:
    return Verdict.model_validate(
        {
            "action_id": action_id,
            "accepted": accepted,
            "predicted": KPIS | {"loss_pct": 13.4},
            "baseline": KPIS,
            "violations": [] if accepted else ["latency_ms over its bound"],
            "impact": "medium",
            "needs_approval": False,
            "sim_mode": "analytical",
            "sim_time_ms": 0.9,
        }
    )


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    path = tmp_path / "actions.db"
    db = Ledger(path)
    steer = ACTION_ADAPTER.validate_python(STEER)
    db.add([steer], [_verdict(steer.action_id, True)], _at(258))
    db.update(steer.action_id, "rolled_back", _at(290), "loss_pct 15.7 -> 21.8 (worse)")
    earlier = ACTION_ADAPTER.validate_python(
        STEER | {"action_id": "act_old", "created_at": "2026-11-08T10:00:00Z"}
    )
    db.add([earlier], [_verdict("act_old", True)], _at(-86400))  # another demo: left out
    return path


def _rows(model: type[TelemetryRecord], start: datetime, end: datetime) -> list[dict[str, Any]]:
    if model is APStats:
        return [
            {"ts": _at(t), "ap": ap, "channel_util": u, "n_clients": n}
            for t, ap, u, n in [
                (1, "ap1", 0.2, 5),
                (9, "ap1", 0.4, 5),
                (12, "ap1", 1.0, 13),
                (1, "ap3", 0.1, 4),
            ]
        ]
    assert model is KPIRecord
    return [
        {"ts": _at(t), "flow_id": f"sta1-{c}", "app_class": c, "throughput_mbps": 0.4}
        | {"latency_ms": lat, "loss_pct": loss}
        for t, c, lat, loss in [
            (3, "video", 8.0, 1.0),
            (5, "video", 12.0, 3.0),
            (3, "web", 4.0, 0.0),
        ]
    ]


def _alerts(start: datetime, end: datetime) -> list[dict[str, Any]]:
    return [
        {"ts": _at(-5).isoformat(), "entity": "ap1", "score": 0.9},  # before the run
        {"ts": _at(240).isoformat(), "entity": "ap1", "score": 0.61},
        {"ts": _at(250).isoformat(), "entity": "ap1", "score": 0.72},
        {"ts": _at(400).isoformat(), "entity": "ap4", "score": 0.55},
    ]


@pytest.fixture
def sources(ledger: Path) -> demo_report.Sources:
    return demo_report.Sources(ledger=ledger, alerts=_alerts, rows=_rows)


def test_the_facts_are_the_runs_own(run_dir: Path, sources: demo_report.Sources) -> None:
    facts = demo_report.collect(run_dir, sources)
    assert (facts["run"]["scenario"], facts["run"]["seed"]) == ("lecture_flash_crowd", 44)
    assert facts["run"]["started_at"] == T0.isoformat()  # the scenario's own start
    assert facts["outcome"]["passed"] is True
    assert facts["by_class"]["web"]["latency_ms_p95"] == 20.4
    assert facts["missing"] == []


def test_the_timeline_groups_events_and_keeps_only_this_run(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    timeline = demo_report.collect(run_dir, sources)["timeline"]
    texts = [(e["t_s"], e["source"], e["text"]) for e in timeline]
    assert texts[0] == (0.0, "scenario", "Scenario started: 20 of 20 stations associated")
    assert texts[1] == (0.01, "scenario", "Co-channel capacity caps: ap1 3.45, ap4 3.45 Mbit/s")
    assert texts[2] == (
        151.2,
        "scenario",
        "3 stations walked to a new AP and re-associated: ap1 x2 (1 failed to associate)",
    )
    assert texts[3] == (210.57, "scenario", "Traffic started: 3 flows (video x2, web x1)")
    assert texts[4] == (240.0, "alert", "Anomaly alert on ap1 x2 (highest score 0.72)")
    assert texts[5][1:] == ("action", "steer_clients sta2, sta12: ap1 → ap3 — rolled back")
    assert texts[6] == (400.0, "alert", "Anomaly alert on ap4 (highest score 0.55)")
    assert texts[-1] == (600.0, "scenario", "Scenario finished")
    assert "ap9" not in json.dumps(timeline)  # the earlier run's events are left out


def test_actions_carry_why_the_verdict_and_what_became_of_them(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    [action] = demo_report.collect(run_dir, sources)["actions"]
    assert action["t_s"] == pytest.approx(256.68)
    assert (action["type"], action["status"], action["accepted"]) == (
        "steer_clients",
        "rolled_back",
        True,
    )
    assert action["note"] == "loss_pct 15.7 -> 21.8 (worse)"
    assert action["predicted"]["loss_pct"] == 13.4


def test_series_are_binned_per_ten_seconds(run_dir: Path, sources: demo_report.Sources) -> None:
    series = demo_report.collect(run_dir, sources)["series"]
    assert series["ap_util"]["ap1"] == [[5.0, pytest.approx(0.3)], [15.0, 1.0]]
    assert series["ap_clients"]["ap3"] == [[5.0, 4.0]]
    assert series["latency_ms"]["video"] == [[5.0, 10.0]]
    assert series["loss_pct"]["web"] == [[5.0, 0.0]]


def test_a_source_that_fails_is_named_not_fatal(run_dir: Path, tmp_path: Path) -> None:
    def down(*args: object) -> list[dict[str, Any]]:
        raise OSError("connection refused")

    gone = demo_report.Sources(ledger=tmp_path / "none.db", alerts=down, rows=down)
    (run_dir / "summary.json").unlink()
    facts = demo_report.collect(run_dir, gone)
    assert (facts["actions"], facts["alerts"], facts["series"], facts["by_class"]) == (
        [],
        [],
        {},
        {},
    )
    assert len(facts["missing"]) == 4
    assert any("alerts" in m and "connection refused" in m for m in facts["missing"])


def test_the_run_fails_when_the_scenario_did(run_dir: Path, sources: demo_report.Sources) -> None:
    collector = json.loads((run_dir / "collector.json").read_text())
    (run_dir / "collector.json").write_text(json.dumps(collector | {"scenario_ok": False}))
    assert demo_report.collect(run_dir, sources)["outcome"]["passed"] is False


def test_a_failed_scenarios_numbers_come_from_its_own_telemetry(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    # live 2026-11-09: a scenario that crashed before its summary left the last good run's
    # summary.json on the VM (from Oct 16), and the demo copied it back as this run's
    collector = json.loads((run_dir / "collector.json").read_text())
    (run_dir / "collector.json").write_text(json.dumps(collector | {"scenario_ok": False}))
    facts = demo_report.collect(run_dir, sources)
    assert facts["by_class"]["video"] == {
        "records": 2,
        "throughput_mbps": 0.4,
        "latency_ms_p50": 10.0,
        "latency_ms_p95": 12.0,
        "loss_pct": 2.0,
    }  # testbed/scenario_plan.py summarize_kpis over the run's kpi rows, not summary.json
    assert facts["by_class_source"] == "InfluxDB (summary.json not used: the scenario failed)"


def test_a_clean_runs_numbers_are_its_summary(run_dir: Path, sources: demo_report.Sources) -> None:
    facts = demo_report.collect(run_dir, sources)
    assert facts["by_class"]["video"]["latency_ms_p95"] == 23.1
    assert facts["by_class_source"] == "summary.json"


class FakeLLM:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.messages: list[dict[str, str]] = []

    def complete_json(
        self,
        messages: Sequence[dict[str, str]],
        schema: type[demo_report.RunSummary],
        *,
        prompt_version: str,
    ) -> LLMResult[demo_report.RunSummary]:
        self.messages = list(messages)
        assert prompt_version == "demo_report_v1"
        if self.error is not None:
            raise self.error
        summary = schema(
            headline="The crowd overloaded ap1; one steer was rolled back.",
            what_happened=["2:31 ten stations reached ap1", "4:16 a steer to ap3"],
            actions_assessment="1 action, rolled back: loss rose.",
            caveats=[],
        )
        return LLMResult(value=summary, model="gpt-oss:120b-cloud", fell_back=False)


def test_the_ai_summary_is_written_from_the_facts_only(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    facts = demo_report.collect(run_dir, sources)
    llm = FakeLLM()
    summary = demo_report.summarise(facts, llm)
    assert summary is not None
    assert summary["model"] == "gpt-oss:120b-cloud"
    assert summary["headline"].startswith("The crowd")
    sent = json.loads(llm.messages[-1]["content"].split("\n", 1)[1])
    assert "series" not in sent  # the peaks instead of every point
    assert sent["peaks"]["ap_util"]["ap1"] == {"max": 1.0, "t_s": 15.0}


@pytest.mark.parametrize("error", [LLMUnavailableError("no model"), ValueError("bad reply")])
def test_no_model_means_no_summary_not_no_report(
    run_dir: Path, sources: demo_report.Sources, error: Exception
) -> None:
    facts = demo_report.collect(run_dir, sources)
    assert demo_report.summarise(facts, FakeLLM(error)) is None


def test_the_page_has_every_section_and_escapes_what_it_shows(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    facts = demo_report.collect(run_dir, sources)
    summary = demo_report.summarise(facts, FakeLLM())
    page = demo_report.render(facts, summary)
    for heading in ("AI summary", "Key numbers", "Timeline", "Control-loop actions", "Charts"):
        assert f">{heading}<" in page
    assert "PASS" in page
    assert "20.4" in page  # web latency p95
    assert "gpt-oss:120b-cloud" in page
    assert "at 10% <b>" not in page  # the action's reason: its markup is shown as text
    assert "at 10% &lt;b&gt;" in page
    assert page.count("<svg") >= 4  # utilisation, clients, latency, loss
    assert "rolled back" in page


def test_without_a_summary_or_series_the_page_says_so(run_dir: Path, tmp_path: Path) -> None:
    def down(*args: object) -> list[dict[str, Any]]:
        raise OSError("down")

    facts = demo_report.collect(run_dir, demo_report.Sources(tmp_path / "x.db", down, down))
    page = demo_report.render(facts, None)
    assert "AI summary unavailable" in page
    assert "No telemetry" in page
    assert "<svg" not in page.split(">Charts<", 1)[1]


def test_build_writes_the_page_and_its_facts_and_rebuilds_from_them(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    path = demo_report.build(run_dir, sources=lambda: sources, llm=FakeLLM)
    assert path == run_dir / "report.html"
    saved = json.loads((run_dir / "report.json").read_text())
    assert saved["summary"]["model"] == "gpt-oss:120b-cloud"

    def not_again() -> demo_report.Sources:
        raise AssertionError("a rebuild re-renders the saved facts")

    path.unlink()
    demo_report.build(run_dir, sources=not_again, llm=lambda: FakeLLM(LLMUnavailableError("x")))
    assert "The crowd overloaded ap1" in path.read_text()  # the saved summary is kept


def test_a_rebuild_tries_the_summary_again_when_there_was_none(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    demo_report.build(run_dir, sources=lambda: sources, llm=lambda: FakeLLM(OSError("down")))
    assert "AI summary unavailable" in (run_dir / "report.html").read_text()
    demo_report.build(run_dir, sources=lambda: sources, llm=FakeLLM)
    assert "The crowd overloaded ap1" in (run_dir / "report.html").read_text()


def test_the_newest_run_is_the_default(tmp_path: Path) -> None:
    for stamp in ("20261109T044424", "20261109T075955", "20261013T075156"):
        (tmp_path / stamp).mkdir()
    (tmp_path / "notes.txt").write_text("")
    assert demo_report.newest_run(tmp_path) == tmp_path / "20261109T075955"
    with pytest.raises(FileNotFoundError, match="no demo run"):
        demo_report.newest_run(tmp_path / "empty")


def test_action_labels_close_together_do_not_overlap(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    facts = demo_report.collect(run_dir, sources)
    [action] = facts["actions"]
    facts["actions"] = [action | {"t_s": t} for t in (290.0, 294.0, 400.0)]
    chart = demo_report.render(facts, None).split("<svg", 2)[2]  # the first chart
    labels = re.findall(r"y='([0-9.]+)' class='marker'>(A\d)<", chart)
    rows = {label: y for y, label in labels}
    assert rows["A1"] != rows["A2"]  # 4 s apart: the second goes one row down
    assert rows["A3"] == rows["A1"]  # far from both: back on the first row


def test_a_broken_event_line_is_skipped_and_named(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    # the 2026-11-09 failure: a run killed mid-write leaves a partial line
    with (run_dir / "events.jsonl").open("a") as out:
        out.write('{"t_s": 601.0, "kind": "fin')
    facts = demo_report.collect(run_dir, sources)
    assert facts["timeline"][-1]["text"] == "Scenario finished"
    assert facts["missing"] == ["events.jsonl: 1 unreadable line left out"]


def test_a_start_time_without_a_timezone_is_refused(run_dir: Path, tmp_path: Path) -> None:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest | {"started_at": "2026-11-09T08:00"})
    )
    (run_dir / "events.jsonl").write_text("")  # no "started" event: the manifest's time is used
    with pytest.raises(ValueError, match="timezone"):
        demo_report.collect(run_dir, demo_report.Sources(tmp_path / "x.db", _alerts, _rows))


def test_the_end_is_when_the_scenario_finished(run_dir: Path, sources: demo_report.Sources) -> None:
    lines = (run_dir / "events.jsonl").read_text().replace('"t_s": 600.0', '"t_s": 412.5')
    (run_dir / "events.jsonl").write_text(lines)  # e.g. stopped early
    assert demo_report.collect(run_dir, sources)["run"]["finished_s"] == 412.5


def test_an_ap_with_another_name_still_gets_a_colour(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    facts = demo_report.collect(run_dir, sources)
    facts["series"]["ap_util"]["guest-ap"] = [[5.0, 0.5]]
    assert "guest-ap" in demo_report.render(facts, None)


def test_the_model_gets_which_sources_are_missing_not_the_errors(
    run_dir: Path, tmp_path: Path
) -> None:
    def down(*args: object) -> list[dict[str, Any]]:
        raise OSError("connection refused to 10.0.0.5:8086 at /secret/path")

    facts = demo_report.collect(run_dir, demo_report.Sources(tmp_path / "x.db", down, down))
    llm = FakeLLM()
    demo_report.summarise(facts, llm)
    sent = json.loads(llm.messages[-1]["content"].split("\n", 1)[1])
    assert sent["missing"] == ["the ledger", "alerts (API)", "telemetry (InfluxDB)"]


def test_a_programming_error_in_a_source_is_not_filed_as_missing(
    run_dir: Path, tmp_path: Path
) -> None:
    def broken(*args: object) -> list[dict[str, Any]]:
        raise AttributeError("a bug, not an outage")

    with pytest.raises(AttributeError):
        demo_report.collect(run_dir, demo_report.Sources(tmp_path / "x.db", broken, _rows))


def test_a_rebuild_reads_the_sources_again_if_some_were_missing(
    run_dir: Path, sources: demo_report.Sources, tmp_path: Path
) -> None:
    def down(*args: object) -> list[dict[str, Any]]:
        raise OSError("down")

    partial = demo_report.Sources(sources.ledger, down, _rows)
    demo_report.build(run_dir, sources=lambda: partial, llm=FakeLLM)
    demo_report.build(run_dir, sources=lambda: sources, llm=FakeLLM)  # the API is back
    saved = json.loads((run_dir / "report.json").read_text())
    assert saved["facts"]["missing"] == []
    assert saved["facts"]["alerts"]


def test_alerts_older_than_the_apis_memory_are_named_not_dropped() -> None:
    api = load_api_config(load_yaml("api.yaml"))
    alerts = demo_report.default_sources(api).alerts
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    with pytest.raises(ValueError, match="keeps alerts for"):
        alerts(long_ago, long_ago + timedelta(minutes=10))


def test_the_model_is_given_the_action_counts_not_left_to_count(
    run_dir: Path, sources: demo_report.Sources
) -> None:
    # live 2026-11-09: given 7 actions (5 kept, 2 rolled back) the model wrote "8 ... 6 kept"
    facts = demo_report.collect(run_dir, sources)
    [action] = facts["actions"]
    facts["actions"] = [action | {"status": s} for s in ("kept", "kept", "rolled_back")]
    llm = FakeLLM()
    demo_report.summarise(facts, llm)
    sent = json.loads(llm.messages[-1]["content"].split("\n", 1)[1])
    assert sent["action_counts"] == {"total": 3, "kept": 2, "rolled_back": 1}
