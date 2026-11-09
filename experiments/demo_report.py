"""The end-of-demo run report: what happened in the scenario that `make demo` just played.

    make demo-report              # rebuild the newest run's report (data/raw/demo/<stamp>/)
    make demo-report DEMO_RUN=<stamp>  # another run (REFRESH=1: read every source again)

`make demo` builds it when the scenario ends (experiments/demo.py) and opens it in the browser:
`report.html`, one self-contained page in the dashboard's Blueprint + Sorbet look, and
`report.json`, the facts it was built from (spec: docs/superpowers/specs/
2026-11-09-demo-run-report-design.md).

- collect(): the facts of the run, from the run folder, the action ledger (read-only), the
  API's alerts and the run's InfluxDB telemetry; a source that cannot be read is named in
  `missing`, never fatal.
- summarise(): a short summary written by the copilot's LLM from those facts only (prompt
  genai/prompts/demo_report_v1.md); None when no model gives a valid one. The model only writes
  text: it calls no tool, controller or AP agent.
- render(): the page; every value from the run is HTML-escaped.
- build(): all three, or a rebuild from `report.json` (the ledger and the API's alerts do not
  outlive the next demo).
"""

from __future__ import annotations

import argparse
import functools
import html
import json
import logging
import math
import re
import sqlite3
import statistics
import urllib.request
import webbrowser
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Protocol, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from api.main import ApiConfig, load_api_config
from api.wiring import ROOT, load_yaml
from common.influx import InfluxConnection, parse_flux_csv, query_csv, rows_query
from common.schemas import MEASUREMENTS, APStats, KPIRecord, TelemetryRecord
from controller.executor.ledger import read_records
from dashboard import theme
from dashboard.views import describe
from genai.llm.client import LLMClient, LLMOutputError, LLMResult, LLMUnavailableError
from genai.tools.tools import MAX_WINDOW_S
from testbed.scenario_plan import summarize_kpis

log = logging.getLogger("experiments.demo_report")
DEMO_RUNS = ROOT / "data" / "raw" / "demo"
PAGE, FACTS = "report.html", "report.json"
PROMPT = ROOT / "genai" / "prompts" / "demo_report_v1.md"
PROMPT_VERSION = PROMPT.stem
BIN_S = 10  # chart resolution
GROUP_S = 10  # arrivals and interference caps this close become one timeline line
ALERT_GAP_S = 30  # alerts on one entity this close become one timeline line
TAIL_S = 30  # actions and alerts this long after the scenario still belong to it
QUERY_TIMEOUT_S = 30.0  # one InfluxDB query
API_TIMEOUT_S = 10.0  # GET /alerts on the local API

T = TypeVar("T")
Facts = dict[str, Any]  # Any: JSON (saved as report.json)
Rows = list[dict[str, Any]]  # Any: the value type depends on the column


@dataclass(frozen=True)
class Sources:
    """Where the facts outside the run folder come from (faked in the tests)."""

    ledger: Path
    alerts: Callable[[datetime, datetime], Rows]  # the API's alerts raised in [start, end)
    rows: Callable[[type[TelemetryRecord], datetime, datetime], Rows]  # the run's telemetry


# ---------------------------------------------------------------- collect


class _Boundary(BaseModel):
    """A file or reply read by the report: the fields it uses, checked (RULEBOOK C-2)."""

    model_config = ConfigDict(extra="ignore")


class Manifest(_Boundary):
    """manifest.json, written by testbed/run_scenario.py when the scenario starts."""

    scenario_id: str
    run_id: str
    seed: int
    duration_s: Annotated[float, Field(gt=0)]
    git_commit: str = ""
    started_at: AwareDatetime


class Collector(_Boundary):
    """collector.json: experiments/run_batch.py play()'s report on the run."""

    passed: bool | None = None
    scenario_ok: bool | None = None
    records: int | None = None
    backlog_records: int | None = None
    max_lag_s: float | None = None
    max_gap_s: float | None = None
    vm_skew_after_s: float | None = None
    failures: dict[str, Any] = Field(default_factory=dict)  # Any: the collector's checks


class Alert(_Boundary):
    """One alert of the API's GET /alerts (api/alerts.py AlertMonitor.tick)."""

    ts: AwareDatetime
    entity: str
    score: float


_AWARE = TypeAdapter(AwareDatetime)


def collect(run_dir: Path, sources: Sources) -> Facts:
    """The facts of one demo run (see the module docstring)."""
    missing: list[str] = []
    raw_manifest = _json(run_dir / "manifest.json")
    if raw_manifest is None:
        raise FileNotFoundError(f"{run_dir} has no manifest.json: not a run folder")
    manifest = Manifest.model_validate(raw_manifest)
    events = _this_run(run_dir / "events.jsonl", missing)
    t0 = _start(manifest, events)
    end = t0 + timedelta(seconds=manifest.duration_s + TAIL_S)
    finished = [e["t_s"] for e in events if e.get("kind") == "finished"]

    raw_collector = _json(run_dir / "collector.json")
    collector = None if raw_collector is None else Collector.model_validate(raw_collector)
    if collector is None:
        missing.append("collector.json (the run's checks): not written")
    summary = _json(run_dir / "summary.json")
    if summary is None:
        missing.append("summary.json (per-class numbers): not written; the scenario failed?")

    actions: Rows = _fetch("the ledger", missing, lambda: _actions(sources.ledger, t0, end), [])
    alerts: Rows = _fetch("alerts (API)", missing, lambda: _alerts(sources.alerts, t0, end), [])
    models: tuple[type[TelemetryRecord], ...] = (APStats, KPIRecord)
    telemetry: dict[type[TelemetryRecord], Rows] = _fetch(
        "telemetry (InfluxDB)",
        missing,
        lambda: {model: sources.rows(model, t0, end) for model in models},
        {model: [] for model in models},
    )
    outcome = _outcome(collector)
    by_class, by_class_source = _by_class(summary, outcome, telemetry[KPIRecord])
    timeline = sorted(
        [*_scenario_lines(events), *_alert_lines(alerts), *_action_lines(actions)],
        key=lambda e: e["t_s"],
    )
    return {
        "run": {
            "stamp": run_dir.name,
            "scenario": manifest.scenario_id,
            "title": manifest.scenario_id.replace("_", " ").capitalize(),
            "run_id": manifest.run_id,
            "seed": manifest.seed,
            "git_commit": manifest.git_commit,
            "started_at": t0.isoformat(),
            "duration_s": manifest.duration_s,
            # when it really ended (a run stopped early); the planned length without the event
            "finished_s": finished[-1] if finished else manifest.duration_s,
        },
        "outcome": outcome,
        "by_class": by_class,
        "by_class_source": by_class_source,
        "timeline": timeline,
        "actions": actions,
        "alerts": alerts,
        "series": _series(telemetry, t0),
        "missing": missing,
    }


def _by_class(
    summary: Mapping[str, Any] | None, outcome: Mapping[str, Any], kpi_rows: Rows
) -> tuple[dict[str, Any], str]:  # Any: JSON
    """The per-class numbers and where they came from. A scenario that failed may have left an
    earlier run's summary.json on the VM (2026-11-09), so its numbers are computed from its own
    telemetry instead, the same way the VM does (testbed/scenario_plan.py summarize_kpis)."""
    if summary is not None and outcome.get("scenario_ok") is not False:
        return summary.get("by_class", {}), "summary.json"
    if not kpi_rows:
        return {}, "none"
    why = "summary.json not used: the scenario failed" if summary is not None else "no summary.json"
    return summarize_kpis(kpi_rows), f"InfluxDB ({why})"


def _json(path: Path) -> Any:  # Any: JSON
    return json.loads(path.read_text()) if path.exists() else None


def _this_run(path: Path, missing: list[str]) -> Rows:
    """The events from the file's last "started" on (folders written before 2026-11-09 hold
    every run of the run id "live"); a line that is not JSON (a run killed mid-write) is left
    out and counted in `missing`."""
    if not path.exists():
        return []
    events, bad = [], 0
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line) if line.strip() else None
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(event, dict) and "t_s" in event and "kind" in event:
            events.append(event)
        elif event is not None:
            bad += 1
    if bad:
        missing.append(f"events.jsonl: {bad} unreadable line{'s' if bad > 1 else ''} left out")
    starts = [i for i, e in enumerate(events) if e["kind"] == "started"]
    return events[starts[-1] :] if starts else events


def _start(manifest: Manifest, events: Rows) -> datetime:
    """When the scenario's clock started: its "started" event (t_s 0), else the manifest's."""
    if events and events[0]["kind"] == "started" and "utc" in events[0]:
        return _AWARE.validate_python(events[0]["utc"])
    return manifest.started_at


# what a source that cannot be read raises: the network, a file, its contents (a bug is not)
SOURCE_ERRORS = (OSError, ValueError, KeyError, sqlite3.Error)


def _fetch(what: str, missing: list[str], read: Callable[[], T], default: T) -> T:
    """read(), or `default` with `what` and the reason added to `missing`."""
    try:
        return read()
    except SOURCE_ERRORS as exc:  # named in the report, never fatal
        log.warning("run report: could not read %s: %s", what, exc)
        missing.append(f"{what}: {exc}")
        return default


def _outcome(collector: Collector | None) -> dict[str, Any]:  # Any: JSON
    if collector is None:
        return {"passed": None}
    return collector.model_dump(exclude_none=True) | {
        # experiments/batch.py run_ok: the collector's checks *and* the scenario's own exit
        "passed": bool(collector.passed) and bool(collector.scenario_ok),
        "collector_passed": collector.passed,
        "scenario_ok": collector.scenario_ok,
    }


def _seconds(ts: datetime, t0: datetime) -> float:
    return round((ts - t0).total_seconds(), 2)


def _actions(ledger: Path, t0: datetime, end: datetime) -> Rows:
    if not ledger.exists():
        raise FileNotFoundError(f"no ledger at {ledger}")
    rows = []
    for r in read_records(ledger):
        a = r.action
        if not t0 <= a.created_at < end:
            continue  # another demo's (the ledger is archived per demo, not per run)
        rows.append(
            {
                "t_s": _seconds(a.created_at, t0),
                "action_id": a.action_id,
                "type": a.type,
                "params": a.params.model_dump(mode="json"),
                "reason": a.reason,
                "source": a.source,
                "accepted": r.verdict.accepted,
                "violations": r.verdict.violations,
                "predicted": r.verdict.predicted.model_dump(),
                "baseline": r.verdict.baseline.model_dump(),
                "status": r.status,
                "note": r.note,
                "measured": r.measured.model_dump() if r.measured is not None else None,
            }
        )
    return rows


def _alerts(fetch: Callable[[datetime, datetime], Rows], t0: datetime, end: datetime) -> Rows:
    rows = []
    for raw in fetch(t0, end):
        a = Alert.model_validate(raw)
        if t0 <= a.ts < end:
            rows.append({"t_s": _seconds(a.ts, t0), "entity": a.entity, "score": a.score})
    return sorted(rows, key=lambda a: a["t_s"])


SERIES: dict[str, tuple[type[TelemetryRecord], str, str]] = {  # chart -> (measurement,
    # the tag that names a line, the field)
    "ap_util": (APStats, "ap", "channel_util"),
    "ap_clients": (APStats, "ap", "n_clients"),
    "latency_ms": (KPIRecord, "app_class", "latency_ms"),
    "loss_pct": (KPIRecord, "app_class", "loss_pct"),
}


def _series(
    rows: Mapping[type[TelemetryRecord], Rows], t0: datetime
) -> dict[str, dict[str, list[list[float]]]]:
    return {
        name: binned(rows[model], tag, field, t0)
        for name, (model, tag, field) in SERIES.items()
        if rows[model]
    }


def binned(rows: Rows, tag: str, field: str, t0: datetime) -> dict[str, list[list[float]]]:
    """{tag value: [[bin middle t_s, mean of the field], ...]} in BIN_S bins from t0."""
    bins: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        t_s = (r["ts"] - t0).total_seconds()
        if t_s >= 0 and r.get(field) is not None:
            bins[r[tag]][int(t_s // BIN_S)].append(float(r[field]))
    return {
        name: [[(b + 0.5) * BIN_S, statistics.fmean(v)] for b, v in sorted(by_bin.items())]
        for name, by_bin in sorted(bins.items())
    }


# the timeline: scenario events, grouped where they come in bursts


def _line(t_s: float, source: str, text: str) -> dict[str, Any]:  # Any: JSON
    return {"t_s": t_s, "source": source, "text": text}


def _bursts(events: Rows, gap_s: float, *, chained: bool = False) -> list[Rows]:
    """Events split where more than gap_s passes from the first of a burst (or, `chained`,
    from the one before)."""
    out: list[Rows] = []
    anchor = -1 if chained else 0
    for e in events:
        if out and e["t_s"] - out[-1][anchor]["t_s"] <= gap_s:
            out[-1].append(e)
        else:
            out.append([e])
    return out


def _counts(values: Iterable[str]) -> str:
    return ", ".join(f"{name} x{n}" for name, n in sorted(Counter(values).items()))


def _scenario_lines(events: Rows) -> list[dict[str, Any]]:  # Any: JSON
    lines = []
    grouped = {"arrived", "interference_cap", "rejoined"}
    for kind in grouped:
        for burst in _bursts([e for e in events if e["kind"] == kind], GROUP_S):
            lines.append(_line(burst[0]["t_s"], "scenario", _burst_text(kind, burst)))
    for e in events:
        if e["kind"] not in grouped:
            lines.append(_line(e["t_s"], "scenario", _event_text(e)))
    return lines


def _burst_text(kind: str, burst: Rows) -> str:
    if kind == "interference_cap":
        caps = ", ".join(
            f"{e['ap']} {e['cap_mbps']}" if e.get("cap_mbps") is not None else f"{e['ap']} lifted"
            for e in burst
        )
        return f"Co-channel capacity caps: {caps} Mbit/s"
    failed = sum(1 for e in burst if not e.get("associated", True))
    ok = _counts(e["ap"] for e in burst if e.get("associated", True))
    verb = "walked to a new AP and re-associated" if kind == "arrived" else "rejoined an AP"
    tail = f" ({failed} failed to associate)" if failed else ""
    return f"{len(burst)} station{'s' if len(burst) > 1 else ''} {verb}: {ok}{tail}"


def _traffic_text(e: Mapping[str, Any]) -> str:
    flows = e.get("flows", [])
    return f"Traffic started: {len(flows)} flows ({_counts(f.rsplit('-', 1)[-1] for f in flows)})"


EVENT_TEXT: dict[str, Callable[[Mapping[str, Any]], str]] = {  # testbed/run_scenario.py kinds
    "started": lambda e: (
        f"Scenario started: {e.get('associated')} of {e.get('stations')} stations associated"
    ),
    "traffic_started": _traffic_text,
    "force_channel": lambda e: f"{e['ap']} forced onto channel {e['channel']} (interference)",
    "ap_down": lambda e: f"{e['ap']} failed (hostapd stopped)",
    "ap_up": lambda e: f"{e['ap']} back up",
    "traffic_duplicate": lambda e: f"{e['sta']} already runs {e['profile']}: not started twice",
    "finished": lambda e: "Scenario finished",
}


def _event_text(e: Mapping[str, Any]) -> str:
    text = EVENT_TEXT.get(e["kind"])
    if text is not None:
        return text(e)
    fields = ", ".join(f"{k}={v}" for k, v in e.items() if k not in ("t_s", "kind"))
    return f"{e['kind'].replace('_', ' ')}: {fields}"  # a kind added later: shown as it is


def _alert_lines(alerts: Rows) -> list[dict[str, Any]]:  # Any: JSON
    by_entity: dict[str, Rows] = defaultdict(list)
    for a in alerts:
        by_entity[a["entity"]].append(a)
    lines = []
    for entity, mine in sorted(by_entity.items()):
        for b in _bursts(mine, ALERT_GAP_S, chained=True):  # one 5 s tick after another
            score = max(a["score"] for a in b)
            times = f" x{len(b)}" if len(b) > 1 else ""
            text = f"Anomaly alert on {entity}{times} (highest score {score:.2f})"
            lines.append(_line(b[0]["t_s"], "alert", text))
    return lines


STATUS_TEXT = {
    "kept": "kept",
    "rolled_back": "rolled back",
    "rejected": "rejected by the twin",
    "verified": "verified, waiting for approval",
    "approved": "approved",
    "applied": "applied, being watched",
    "failed": "failed to apply (undone)",
    "rollback_failed": "rollback failed (needs an operator)",
}


def status_text(a: Mapping[str, Any]) -> str:
    """An action's ledger status in words ("rolled back")."""
    return STATUS_TEXT.get(a["status"], str(a["status"]))


def _action_lines(actions: Rows) -> list[dict[str, Any]]:  # Any: JSON
    # describe(): the dashboard's wording, so an action reads the same in both
    return [_line(a["t_s"], "action", f"{describe(a)} — {status_text(a)}") for a in actions]


# ---------------------------------------------------------------- summarise


class RunSummary(BaseModel):
    """The AI summary at the top of the report (genai/prompts/demo_report_v1.md)."""

    model_config = ConfigDict(extra="forbid")

    headline: Annotated[str, Field(min_length=1, max_length=240)]
    what_happened: Annotated[
        list[Annotated[str, Field(max_length=300)]], Field(min_length=2, max_length=5)
    ]
    actions_assessment: Annotated[str, Field(max_length=500)]
    caveats: Annotated[list[Annotated[str, Field(max_length=300)]], Field(max_length=3)]


class SummaryClient(Protocol):
    """What summarise() needs of genai.llm.client.LLMClient."""

    def complete_json(
        self, messages: Sequence[dict[str, str]], schema: type[RunSummary], *, prompt_version: str
    ) -> LLMResult[RunSummary]: ...


def summarise(facts: Facts, client: SummaryClient) -> dict[str, Any] | None:  # Any: JSON
    """The AI summary of the run, from the facts only; None when no model gives a valid one."""
    # every point of the charts as its peak; the alerts are in the timeline already
    for_model = {k: v for k, v in facts.items() if k not in ("series", "alerts")}
    for_model["peaks"] = peaks(facts)
    # counted here: given 7 actions the model once wrote "8 ... 6 kept" (2026-11-09)
    statuses = Counter(a["status"] for a in facts["actions"])
    for_model["action_counts"] = {"total": len(facts["actions"]), **statuses}
    # which sources are missing, not their errors (hosts, paths): those are not run facts
    for_model["missing"] = [m.split(":", 1)[0] for m in facts["missing"]]
    messages = [
        {"role": "system", "content": PROMPT.read_text()},
        {"role": "user", "content": f"Facts:\n{json.dumps(for_model)}"},
    ]
    try:
        result = client.complete_json(messages, RunSummary, prompt_version=PROMPT_VERSION)
    except (LLMUnavailableError, LLMOutputError, OSError, ValueError) as exc:
        log.warning("run report: no AI summary: %s", exc)
        return None
    return result.value.model_dump() | {"model": result.model, "fell_back": result.fell_back}


def peaks(facts: Facts) -> dict[str, dict[str, dict[str, float]]]:
    """The highest value of every line of every chart, and when."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for name, lines in facts["series"].items():
        out[name] = {}
        for line, points in lines.items():
            t_s, value = max(points, key=lambda p: p[1])
            out[name][line] = {"max": round(value, 3), "t_s": t_s}
    return out


# ---------------------------------------------------------------- render

AP_COLOURS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")  # dataviz validator: pass (contrast
# warns for the last two on white: every line is labelled at its end and has a data table)
CLASS_COLOURS = {"video": "#7B4FC4", "web": "#C23B7A", "bulk": "#4F6B12"}  # = the dashboard's


@dataclass(frozen=True)
class Chart:
    """One chart: a SERIES entry, its labels, the lowest top of its axis and the value format."""

    name: str
    title: str
    unit: str
    floor: float
    fmt: str


CHARTS = (
    Chart("ap_util", "AP channel utilisation", "share of capacity", 1.0, "{:.0%}"),
    Chart("ap_clients", "Clients per AP", "stations", 5.0, "{:.0f}"),
    Chart(
        "latency_ms", "Latency per traffic class", "ms, mean of the class's flows", 10.0, "{:.1f}"
    ),
    Chart("loss_pct", "Loss per traffic class", "%, mean of the class's flows", 5.0, "{:.1f}"),
)


def _e(value: Any) -> str:  # Any: whatever the facts hold
    return html.escape(str(value), quote=True)


def mmss(t_s: float) -> str:
    """Seconds into the run as m:ss, the scenario clock's format (3:30)."""
    whole = max(0, int(t_s))
    return f"{whole // 60}:{whole % 60:02d}"


def render(facts: Facts, summary: Mapping[str, Any] | None) -> str:
    """The report page."""
    run = facts["run"]
    body = "".join(
        [
            _header(facts),
            _summary_card(summary),
            _numbers_card(facts),
            _timeline_card(facts),
            _actions_card(facts),
            _charts_card(facts),
            _missing_card(facts),
        ]
    )
    title = f"Demo report: {run['title']} ({run['stamp']})"
    return (
        "<!doctype html>\n<html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_e(title)}</title>"
        f"<link rel='stylesheet' href='{_e(theme.FONTS_URL)}'>"
        f"<style>{_CSS}</style></head><body><main>{body}</main></body></html>\n"
    )


def _card(heading: str, inner: str, colour: str = theme.WHITE) -> str:
    return (
        f"<section class='card' style='background:{colour}'><h2>{_e(heading)}</h2>{inner}</section>"
    )


def _header(facts: Facts) -> str:
    run, outcome = facts["run"], facts["outcome"]
    passed = outcome.get("passed")
    verdict = {True: ("✓ PASS", "pass"), False: ("✕ FAIL", "fail"), None: ("? unknown", "unknown")}
    word, css = verdict[passed]
    started = datetime.fromisoformat(run["started_at"])
    ended = started + timedelta(seconds=run["finished_s"])
    facts_row = [
        ("Scenario", run["title"]),
        ("Seed", run["seed"]),
        ("Run id", run["run_id"]),
        ("Started (UTC)", started.strftime("%Y-%m-%d %H:%M:%S")),
        ("Ended (UTC)", ended.strftime("%H:%M:%S")),
        ("Duration", mmss(run["duration_s"])),
        ("Git commit", run["git_commit"] or "—"),
    ]
    checks = [
        ("Scenario finished cleanly", outcome.get("scenario_ok")),
        ("Collector checks", outcome.get("collector_passed")),
    ]
    quality = [
        ("Telemetry records", outcome.get("records")),
        ("Max lag", _unit(outcome.get("max_lag_s"), "s")),
        ("Max gap", _unit(outcome.get("max_gap_s"), "s")),
    ]
    dl = "".join(f"<div><dt>{_e(k)}</dt><dd>{_e(v)}</dd></div>" for k, v in facts_row + quality)
    ticks = "".join(
        f"<li>{'✓' if ok else '✕' if ok is False else '?'} {_e(name)}</li>" for name, ok in checks
    )
    return (
        "<header class='card head'>"
        f"<p class='kicker'>Digital-twin SDN · live demo run report</p>"
        f"<h1>{_e(run['title'])}</h1>"
        f"<p class='verdict {css}'>{_e(word)}</p><ul class='checks'>{ticks}</ul>"
        f"<dl class='facts'>{dl}</dl></header>"
    )


def _unit(value: Any, unit: str) -> str:  # Any: a JSON number or None
    return "—" if value is None else f"{float(value):.2f} {unit}"


def _summary_card(summary: Mapping[str, Any] | None) -> str:
    if summary is None:
        inner = (
            "<p class='muted'>AI summary unavailable: no language model answered with a valid "
            "summary. The facts below are complete without it; "
            "<code>make demo-report</code> tries again.</p>"
        )
        return _card("AI summary", inner, theme.LAVENDER)
    points = "".join(f"<li>{_e(p)}</li>" for p in summary["what_happened"])
    caveats = "".join(f"<li>{_e(c)}</li>" for c in summary["caveats"])
    fell_back = " (local fallback model)" if summary.get("fell_back") else ""
    inner = (
        f"<p class='headline'>{_e(summary['headline'])}</p><ul>{points}</ul>"
        f"<p>{_e(summary['actions_assessment'])}</p>"
        + (f"<p class='label'>Caveats</p><ul>{caveats}</ul>" if caveats else "")
        + f"<p class='muted small'>Written by {_e(summary['model'])}{_e(fell_back)} from the facts"
        " in this report only; check it against them.</p>"
    )
    return _card("AI summary", inner, theme.LAVENDER)


def _numbers_card(facts: Facts) -> str:
    by_class = facts["by_class"]
    if not by_class:
        return _card("Key numbers", "<p class='muted'>Per-class numbers not available.</p>")
    columns = (
        ("throughput_mbps", "Throughput", "Mbit/s"),
        ("latency_ms_p50", "Latency p50", "ms"),
        ("latency_ms_p95", "Latency p95", "ms"),
        ("loss_pct", "Loss", "%"),
    )
    head = "".join(f"<th>{_e(t)} <span class='muted'>{_e(u)}</span></th>" for _, t, u in columns)
    rows = "".join(
        f"<tr><th>{_e(name)}</th>"
        + "".join(f"<td>{_e(_num(values.get(key)))}</td>" for key, _, _ in columns)
        + "</tr>"
        for name, values in sorted(by_class.items())
    )
    inner = (
        f"<table><thead><tr><th>Class</th>{head}</tr></thead><tbody>{rows}</tbody></table>"
        "<p class='muted small'>Over the whole run, from every flow's probes. Source: "
        f"{_e(facts['by_class_source'])}.</p>"
    )
    return _card("Key numbers", inner)


THREE_DIGITS = 10  # below it a number keeps 3 significant digits (0.357), above it 1 decimal


def _num(value: Any) -> str:  # Any: a JSON number or None
    if value is None:
        return "—"
    number = float(value)
    return f"{number:.3g}" if abs(number) < THREE_DIGITS else f"{number:.1f}"


SOURCE_LABELS = {"scenario": "Scenario", "alert": "⚠ Alert", "action": "⚙ Action"}


def _timeline_card(facts: Facts) -> str:
    if not facts["timeline"]:
        return _card("Timeline", "<p class='muted'>No events recorded.</p>")
    rows = "".join(
        f"<tr class='src-{_e(e['source'])}'><td class='time'>{mmss(e['t_s'])}</td>"
        f"<td><span class='tag'>{_e(SOURCE_LABELS.get(e['source'], e['source']))}</span></td>"
        f"<td>{_e(e['text'])}</td></tr>"
        for e in facts["timeline"]
    )
    inner = (
        "<table class='timeline'><thead><tr><th>Time</th><th>From</th><th>What happened</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )
    return _card("Timeline", inner)


STATUS_CSS = {"kept": "good", "rolled_back": "bad", "rejected": "muted", "rollback_failed": "bad"}


def _actions_card(facts: Facts) -> str:
    actions = facts["actions"]
    if not actions:
        return _card(
            "Control-loop actions",
            "<p class='muted'>The control loop proposed no action in this run.</p>",
            theme.MINT,
        )
    counts = Counter(status_text(a) for a in actions)
    tally = ", ".join(f"{n} {s}" for s, n in counts.most_common())
    rows = "".join(_action_row(i, a) for i, a in enumerate(actions, 1))
    inner = (
        f"<p>{len(actions)} action{'s' if len(actions) > 1 else ''}: {_e(tally)}.</p>"
        "<table><thead><tr><th>#</th><th>Time</th><th>Action</th><th>Why</th>"
        "<th>Twin verdict <span class='muted'>(predicted vs before)</span></th><th>Outcome</th>"
        f"<th>Measured</th></tr></thead><tbody>{rows}</tbody></table>"
    )
    return _card("Control-loop actions", inner, theme.MINT)


KPI_SHORT = (
    ("throughput_mbps", "thr", "Mbit/s"),
    ("latency_ms", "lat", "ms"),
    ("loss_pct", "loss", "%"),
)


def _kpis(values: Mapping[str, float] | None) -> str:
    if values is None:
        return "—"
    return ", ".join(f"{s} {_num(values.get(k))} {u}" for k, s, u in KPI_SHORT)


def _action_row(i: int, a: dict[str, Any]) -> str:  # Any: JSON
    verdict = "accepted" if a["accepted"] else "rejected: " + "; ".join(a["violations"])
    compare = "; ".join(
        f"{s} {_num(a['baseline'].get(k))} → {_num(a['predicted'].get(k))} {u}"
        for k, s, u in KPI_SHORT
    )
    status = status_text(a)
    note = f"<div class='muted small'>{_e(a['note'])}</div>" if a["note"] else ""
    return (
        f"<tr><td>A{i}</td><td class='time'>{mmss(a['t_s'])}</td>"
        f"<td><code>{_e(describe(a))}</code></td><td>{_e(a['reason'])}</td>"
        f"<td>{_e(verdict)}<div class='muted small'>{_e(compare)}</div></td>"
        f"<td><span class='status {STATUS_CSS.get(a['status'], '')}'>{_e(status)}</span>{note}</td>"
        f"<td class='small'>{_e(_kpis(a['measured']))}</td></tr>"
    )


def _charts_card(facts: Facts) -> str:
    series = facts["series"]
    if not series:
        return _card("Charts", "<p class='muted'>No telemetry for this run: no charts.</p>")
    overlay = Overlay(
        duration_s=facts["run"]["duration_s"],
        actions=[(a["t_s"], f"A{i}", describe(a)) for i, a in enumerate(facts["actions"], 1)],
        alerts=[(a["t_s"], a["entity"], a["score"]) for a in facts["alerts"]],
    )
    charts = [
        _chart(chart, series[chart.name], _colours(chart.name, series[chart.name]), overlay)
        for chart in CHARTS
        if series.get(chart.name)
    ]
    key = (
        "<p class='muted small'>Dashed lines: the control loop's actions (A1, A2, … as in the"
        " table above). Red ticks on top: anomaly alerts. 10-second means; hover a point for its"
        " value.</p>"
    )
    return _card("Charts", key + "".join(charts))


def _colours(name: str, lines: Mapping[str, Any]) -> dict[str, str]:
    if name.startswith("ap_"):  # by AP number, so a colour always means the same AP
        return {ap: AP_COLOURS[_ap_slot(ap, i) % len(AP_COLOURS)] for i, ap in enumerate(lines)}
    return {c: CLASS_COLOURS.get(c, theme.NAVY) for c in lines}


def _ap_slot(ap: str, position: int) -> int:
    """apN -> N - 1; an AP named otherwise takes its place in the legend."""
    number = re.fullmatch(r"ap(\d+)", ap)
    return int(number.group(1)) - 1 if number else position


W, H = 720, 262
LEFT, RIGHT, TOP, BOTTOM = 52, 78, 50, 30  # TOP: the action labels' strip, then the alerts'
MARKER_ROWS, MARKER_LABEL_W = 3, 26  # action labels (A1, A10): rows, the width each needs


@dataclass(frozen=True)
class Overlay:
    """What every chart marks: the actions (t_s, A<n>, text) and alerts (t_s, entity, score)."""

    duration_s: float
    actions: Sequence[tuple[float, str, str]]
    alerts: Sequence[tuple[float, str, float]]


def _chart(
    chart: Chart,
    lines: Mapping[str, list[list[float]]],
    colours: Mapping[str, str],
    overlay: Overlay,
) -> str:
    title, fmt, duration_s = chart.title, chart.fmt, overlay.duration_s
    top = max([chart.floor, *(v for pts in lines.values() for _, v in pts)])
    y_max = _nice(top)

    def x(t: float) -> float:
        return LEFT + (W - LEFT - RIGHT) * min(max(t, 0.0), duration_s) / duration_s

    def y(v: float) -> float:
        return TOP + (H - TOP - BOTTOM) * (1 - v / y_max)

    parts = []
    for frac in (0.0, 0.5, 1.0):  # recessive guides, labelled on the left
        v = y_max * frac
        parts.append(
            f"<line x1='{LEFT}' x2='{W - RIGHT}' y1='{y(v):.1f}' y2='{y(v):.1f}' class='guide'/>"
            f"<text x='{LEFT - 6}' y='{y(v) + 4:.1f}' class='axis' text-anchor='end'>"
            f"{_e(fmt.format(v))}</text>"
        )
    for tick in range(0, int(duration_s) + 1, 60):
        parts.append(
            f"<text x='{x(tick):.1f}' y='{H - 10}' class='axis' text-anchor='middle'>"
            f"{mmss(tick)}</text>"
        )
    row_end = [-math.inf] * MARKER_ROWS  # where each row's last label ends
    for t, label, text in overlay.actions:
        # the first row this label fits on without touching the one before it (else the last)
        row = next((r for r, end in enumerate(row_end) if x(t) > end), MARKER_ROWS - 1)
        row_end[row] = x(t) + MARKER_LABEL_W
        parts.append(
            f"<g><title>{_e(label)} at {mmss(t)}: {_e(text)}</title>"
            f"<line x1='{x(t):.1f}' x2='{x(t):.1f}' y1='{14 + 12 * row}' y2='{H - BOTTOM}'"
            " class='action'/>"
            f"<text x='{x(t) + 3:.1f}' y='{12 + 12 * row}' class='marker'>{_e(label)}"
            "</text></g>"
        )
    for t, entity, score in overlay.alerts:
        parts.append(
            f"<g><title>Alert at {mmss(t)} on {_e(entity)} (score {score:.2f})</title>"
            f"<rect x='{x(t) - 1.5:.1f}' y='{TOP - 9}' width='3' height='8' class='alert'/></g>"
        )
    ends = []
    for name, pts in lines.items():
        colour = colours[name]
        path = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in pts)
        parts.append(f"<polyline points='{path}' fill='none' stroke='{colour}' class='series'/>")
        for t, v in pts:  # hit targets bigger than the line, each with its value
            parts.append(
                f"<circle cx='{x(t):.1f}' cy='{y(v):.1f}' r='6' class='hit'>"
                f"<title>{_e(name)} at {mmss(t)}: {_e(fmt.format(v))}</title></circle>"
            )
        ends.append((y(pts[-1][1]), x(pts[-1][0]), name, colour))
    parts += _end_labels(ends)
    legend = "".join(
        f"<span class='key'><i style='background:{c}'></i>{_e(n)}</span>"
        for n, c in colours.items()
    )
    svg = (
        f"<svg viewBox='0 0 {W} {H}' role='img' aria-label='{_e(title)} over the run'>"
        f"{''.join(parts)}</svg>"
    )
    return (
        f"<figure><figcaption><b>{_e(title)}</b> <span class='muted'>({_e(chart.unit)})</span>"
        f"<span class='legend'>{legend}</span></figcaption>{svg}"
        f"{_data_table(lines, fmt)}</figure>"
    )


def _nice(top: float) -> float:
    """A round axis maximum at or above `top`."""
    step = 10 ** math.floor(math.log10(top)) if top > 0 else 1
    return next(m * step for m in (1, 2, 2.5, 5, 10) if m * step >= top)  # 10: always enough


def _end_labels(ends: list[tuple[float, float, str, str]]) -> list[str]:
    """Each line's name at its last point, nudged apart so none overlap (12 px apart)."""
    out, last_y = [], -math.inf
    for y_end, x_end, name, colour in sorted(ends):
        y_label = max(y_end, last_y + 12)
        last_y = y_label
        out.append(
            f"<circle cx='{x_end:.1f}' cy='{y_end:.1f}' r='4' fill='{colour}' class='end'/>"
            f"<text x='{x_end + 8:.1f}' y='{y_label + 4:.1f}' class='label'>{_e(name)}</text>"
        )
    return out


def _data_table(lines: Mapping[str, list[list[float]]], fmt: str) -> str:
    names = list(lines)
    by_time: dict[float, dict[str, float]] = defaultdict(dict)
    for name, pts in lines.items():
        for t, v in pts:
            by_time[t][name] = v
    head = "".join(f"<th>{_e(n)}</th>" for n in names)
    rows = "".join(
        f"<tr><td>{mmss(t)}</td>"
        + "".join(f"<td>{_e(fmt.format(vals[n])) if n in vals else '—'}</td>" for n in names)
        + "</tr>"
        for t, vals in sorted(by_time.items())
    )
    return (
        "<details><summary>Data table</summary>"
        f"<table class='data'><thead><tr><th>Time</th>{head}</tr></thead><tbody>{rows}</tbody>"
        "</table></details>"
    )


def _missing_card(facts: Facts) -> str:
    if not facts["missing"]:
        return ""
    items = "".join(f"<li>{_e(m)}</li>" for m in facts["missing"])
    return _card("Not in this report", f"<ul>{items}</ul>", theme.YELLOW)


_CSS = f"""
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: {theme.PAGE}; color: {theme.NAVY}; font: 15px/1.5 {theme.BODY};
  background-image: linear-gradient({theme.GRID} 1px, transparent 1px),
    linear-gradient(90deg, {theme.GRID} 1px, transparent 1px);
  background-size: 24px 24px; }}
main {{ max-width: 1040px; margin: 0 auto; padding: 24px 16px 48px; }}
.card {{ border: 2px solid {theme.NAVY}; box-shadow: {theme.SHADOW}; border-radius: 6px;
  padding: 18px 20px; margin: 0 0 22px; overflow-x: auto; }}
.head {{ background: {theme.YELLOW}; }}
h1, h2 {{ font-family: {theme.DISPLAY}; margin: 0 0 10px; letter-spacing: .02em; }}
h1 {{ font-size: 30px; }} h2 {{ font-size: 20px; }}
.kicker {{ margin: 0; text-transform: uppercase; font-size: 12px; letter-spacing: .12em; }}
.verdict {{ display: inline-block; font: 700 20px {theme.DISPLAY}; padding: 2px 12px;
  border: 2px solid {theme.NAVY}; border-radius: 4px; margin: 0 12px 8px 0; }}
.verdict.pass {{ background: {theme.MINT}; }} .verdict.fail {{ background: {theme.CORAL}; }}
.verdict.unknown {{ background: {theme.GREY_ZONE}; }}
.checks {{ display: inline-flex; gap: 16px; list-style: none; padding: 0; margin: 0; }}
.facts {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px 16px; margin: 12px 0 0; }}
.facts dt {{ font-size: 12px; color: {theme.MUTED}; }} .facts dd {{ margin: 0; font-weight: 600; }}
.headline {{ font-size: 18px; font-weight: 600; }}
.label {{ font-weight: 700; margin-bottom: 0; }}
.muted {{ color: {theme.MUTED}; }} .small {{ font-size: 13px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ border: 1px solid {theme.NAVY}; padding: 5px 8px; text-align: left;
  vertical-align: top; }}
thead th {{ background: {theme.TRACK}; }}
td.time {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
.tag {{ font-size: 12px; font-weight: 700; white-space: nowrap; }}
tr.src-alert td {{ background: #FFF1EE; }} tr.src-action td {{ background: #F1EEFF; }}
.status {{ font-weight: 700; padding: 1px 6px; border-radius: 3px;
  border: 1px solid {theme.NAVY}; }}
.status.good {{ background: {theme.MINT_BOX}; }} .status.bad {{ background: {theme.CORAL_ZONE}; }}
.status.muted {{ background: {theme.GREY_ZONE}; }}
code {{ font-size: 13px; }}
figure {{ margin: 18px 0 0; }} figcaption {{ margin-bottom: 4px; }}
.legend {{ float: right; }} .key {{ margin-left: 12px; font-size: 13px; }}
.key i {{ display: inline-block; width: 14px; height: 3px; margin-right: 5px;
  vertical-align: middle; }}
svg {{ width: 100%; height: auto; display: block; background: {theme.WHITE}; }}
svg .guide {{ stroke: {theme.LINE}; stroke-width: 1; }}
svg .axis {{ fill: {theme.MUTED}; font-size: 11px; }}
svg .series {{ stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
svg .hit {{ fill: transparent; }} svg .hit:hover {{ fill: {theme.NAVY}; fill-opacity: .25; }}
svg .end {{ stroke: {theme.WHITE}; stroke-width: 2; }}
svg .label {{ fill: {theme.NAVY}; font-size: 12px; font-weight: 600; }}
svg .action {{ stroke: {theme.NAVY}; stroke-width: 1.5; stroke-dasharray: 4 3; }}
svg .marker {{ fill: {theme.NAVY}; font-size: 11px; font-weight: 700; }}
svg .alert {{ fill: {theme.RED}; }}
details {{ margin-top: 4px; font-size: 13px; }}
table.data td {{ font-variant-numeric: tabular-nums; }}
@media print {{ body {{ background: {theme.WHITE}; }}
  .card {{ box-shadow: none; break-inside: avoid; }} }}
"""


# ---------------------------------------------------------------- build


def build(
    run_dir: Path,
    *,
    sources: Callable[[], Sources],
    llm: Callable[[], SummaryClient],
    refresh: bool = False,
) -> Path:
    """Write report.html (and report.json) for `run_dir`; returns the page's path. Saved facts
    are reused unless `refresh` or a source was missing when they were collected (it may be
    back); the summary is asked for again only if there was none."""
    saved = _json(run_dir / FACTS)
    if saved is None or refresh or saved["facts"]["missing"]:
        facts, summary = collect(run_dir, sources()), None
    else:
        facts, summary = saved["facts"], saved["summary"]
    if summary is None:
        summary = summarise(facts, llm())
    (run_dir / FACTS).write_text(json.dumps({"facts": facts, "summary": summary}, indent=1))
    page = run_dir / PAGE
    page.write_text(render(facts, summary))
    return page


def default_sources(api: ApiConfig) -> Sources:
    """The live ledger, the API's alerts and the run's telemetry in InfluxDB."""

    def alerts(start: datetime, end: datetime) -> Rows:
        since = math.ceil((datetime.now(start.tzinfo) - start).total_seconds())
        if since > MAX_WINDOW_S:  # the run's first alerts are gone: say so, not a partial list
            raise ValueError(f"the API keeps alerts for {MAX_WINDOW_S // 60} min only")
        url = f"http://{api.host}:{api.port}/alerts?since={max(since, 0)}"
        with urllib.request.urlopen(url, timeout=API_TIMEOUT_S) as resp:
            return list(json.loads(resp.read())["alerts"])

    connection = functools.cache(InfluxConnection.from_env)  # on first use: may be missing

    def rows(model: type[TelemetryRecord], start: datetime, end: datetime) -> Rows:
        conn = connection()
        flux = rows_query(conn.bucket, MEASUREMENTS[model], start, end, run_id=api.run_id)
        return parse_flux_csv(query_csv(conn, flux, QUERY_TIMEOUT_S), model)

    return Sources(ledger=ROOT / api.ledger, alerts=alerts, rows=rows)


def newest_run(root: Path = DEMO_RUNS) -> Path:
    """The newest demo run folder (folders are named by their UTC start stamp)."""
    runs = sorted(p for p in root.glob("*T*") if p.is_dir()) if root.exists() else []
    if not runs:
        raise FileNotFoundError(f"no demo run under {root}: run `make demo` first")
    return runs[-1]


def main(argv: list[str] | None = None) -> int:
    """`make demo-report`: (re)build a run's report and open it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", help="the run's stamp under data/raw/demo/ (default: newest)")
    parser.add_argument("--refresh", action="store_true", help="read the sources again")
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_dir = DEMO_RUNS / args.run if args.run else newest_run()
    api = load_api_config(load_yaml("api.yaml"))
    build_and_open(run_dir, api, refresh=args.refresh, show=not args.no_open)
    return 0


def build_and_open(
    run_dir: Path, api: ApiConfig, *, refresh: bool = False, show: bool = True
) -> Path:
    """build() from the live sources and the copilot's model, then open the page (`show`)."""
    page = build(
        run_dir, sources=lambda: default_sources(api), llm=LLMClient.from_config, refresh=refresh
    )
    print(f"DEMO report {page}", flush=True)
    if show:
        webbrowser.open(page.as_uri())
    return page


if __name__ == "__main__":
    raise SystemExit(main())
