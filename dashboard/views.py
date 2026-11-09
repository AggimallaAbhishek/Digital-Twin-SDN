"""P6.1 dashboard view logic: the API's JSON turned into what each panel shows. Pure functions,
no Streamlit, so they are unit-tested (tests/unit/test_dashboard_views.py).

Panels (deviation #19): the status banner and its four numbers (`status`, `tiles`); the "What
is happening" timeline (`timeline`, with `waiting_steps`, `alert_groups`, `plain_action`) and
the root-cause report in it (`rca_view`); the campus map (`map_layers`, `latest_steer`); the
charts (`kpi_series`, `twin_vs_live`). `safe_html` is how any API text goes into the page.
"""

from __future__ import annotations

import html
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean
from typing import Any

Row = dict[str, Any]  # Any: JSON values for Altair / Streamlit tables

COVERAGE_M = 30.0  # RSSI >= -75 dBm, the steering bound (docs/scenario.md)
INTERFERE_M = 60.0  # same-channel APs closer than this share airtime (config/campus_v1.yaml)
BUSY, CONGESTED = 0.6, 0.8  # P4.5-A: utilisation of 0.8 or more is congested
KPIS = (  # (label, Verdict / KPIValues field)
    ("throughput Mbit/s", "throughput_mbps"),
    ("latency ms", "latency_ms"),
    ("loss %", "loss_pct"),
)


def safe_html(value: object) -> str:
    """Text from the API (which the LLM may have written) for st.markdown's HTML: escaped, with
    line breaks as <br>. A blank line would end the HTML block and let Markdown after it render,
    an image from any address for one (rule L-6)."""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return html.escape(text).replace("\n", "<br>")


_MD_PUNCTUATION = re.compile(r"([!-/:-@\[-`{-~])")  # every ASCII punctuation mark


def md_literal(value: object) -> str:
    """Text for st.error / st.toast, which render Markdown: every ASCII punctuation mark
    backslash-escaped (CommonMark shows it as typed), so no image, link or $…$ maths can come
    from the API's text (rule L-6)."""
    return _MD_PUNCTUATION.sub(r"\\\1", " ".join(str(value).split()))


_BOLD = re.compile(r"\*\*((?:(?!<br>).)+?)\*\*")  # **…** within one line


def rich_html(value: object) -> str:
    """Like safe_html, for the model's prose: its **bold** as bold, and nothing else."""
    return _BOLD.sub(r"<b>\1</b>", safe_html(value))


def band(util: float) -> str:
    """The load band a utilisation (0 to 1) falls in: calm, busy or congested."""
    if util >= CONGESTED:
        return "congested"
    return "busy" if util >= BUSY else "calm"


def map_layers(topology: dict[str, Any]) -> tuple[list[Row], list[Row]]:
    """(AP rows, station rows) for the campus map, from GET /topology."""
    clients: dict[str, int] = {}
    for s in topology["stations"]:
        if s["ap"]:
            clients[s["ap"]] = clients.get(s["ap"], 0) + 1
    aps = []
    for a in topology["aps"]:
        n = clients.get(a["name"], 0)
        channel = f"ch {a['channel']}"
        if a["up"]:
            load = band(a["util"])
            label = f"{a['name']} · {a['util']:.0%} · {n}"  # the channel is drawn below it
        else:
            load, label = "down", f"{a['name']} · down"
        aps.append(
            {
                "name": a["name"],
                "x": a["position"][0],
                "y": a["position"][1],
                "channel": channel,
                "load": round(a["util"], 3),
                "band": load,
                "clients": n,
                "label": label,
                "coverage_m": COVERAGE_M,
                "shares_channel_with": _cochannel(a, topology["aps"]),
            }
        )
    stations = [
        {"name": s["name"], "x": s["position"][0], "y": s["position"][1], "ap": s["ap"] or "no AP"}
        for s in topology["stations"]
    ]
    return aps, stations


def _cochannel(ap: dict[str, Any], aps: list[dict[str, Any]]) -> list[str]:
    """The other APs that are up on the same channel close enough to share its airtime."""
    if not ap["up"]:
        return []
    return sorted(
        o["name"]
        for o in aps
        if o["name"] != ap["name"]
        and o["up"]
        and o["channel"] == ap["channel"]
        and math.dist(o["position"], ap["position"]) < INTERFERE_M
    )


def waiting_steps(actions: list[Row]) -> dict[str, str]:
    """The actions an operator has to act on, by id, with the next step: approve (verified,
    needs approval) or apply (approved, not yet applied)."""
    steps = {}
    for r in actions:
        if r["status"] == "verified" and r["verdict"]["needs_approval"]:
            steps[r["action_id"]] = "approve"
        elif r["status"] == "approved":
            steps[r["action_id"]] = "apply"
    return steps


def describe(action: Row) -> str:
    """One line a person reads: `set_ap_channel ap3 → channel 11`."""
    p, kind = action["params"], action["type"]
    if kind == "set_ap_channel":
        return f"{kind} {p['ap']} → channel {p['channel']}"
    if kind == "steer_clients":
        return f"{kind} {', '.join(p['stations'])}: {p['from_ap']} → {p['to_ap']}"
    if kind == "set_ap_tx_power":
        return f"{kind} {p['ap']} → {p['dbm']} dBm"
    if kind == "ap_admin_state":
        return f"{kind} {p['ap']} → {p['state']}"
    return f"{kind} {', '.join(f'{k}={v}' for k, v in sorted(p.items()))}"


def plain_action(action: Row) -> str:
    """What an action does, in words for the audience: `Move 3 clients ap1 → ap3`. A type
    without its own wording falls back to describe()."""
    words = _ACTION_WORDS.get(action["type"])
    return words(action["params"]) if words else describe(action)


def _plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def _clients(n: int) -> str:
    return f"{n} {_plural(n, 'client')}"


QUEUE_WORDS = {  # common/schemas.py QOS_QUEUE_IDS: 0 best effort, 1 priority, 2 background
    0: "Put {who} back to best effort",
    1: "Give {who} priority",
    2: "Move {who} to the background queue",
}

_ACTION_WORDS: dict[str, Callable[[Row], str]] = {
    "steer_clients": lambda p: (
        f"Move {_clients(len(p['stations']))} from {p['from_ap']} to {p['to_ap']}"
    ),
    "set_ap_channel": lambda p: f"Move {p['ap']} to channel {p['channel']}",
    "set_ap_tx_power": lambda p: f"Set {p['ap']} power to {p['dbm']:g} dBm",
    "ap_admin_state": lambda p: f"Turn {p['ap']} {'on' if p['state'] == 'up' else 'off'}",
    "set_qos_queue": lambda p: QUEUE_WORDS.get(
        p["queue_id"], f"Put {{who}} in queue {p['queue_id']}"
    ).format(who=_traffic(p["match"])),
    "rate_limit_flow": lambda p: f"Cap flow {p['flow_id']} at {p['max_mbps']:g} Mbit/s",
    "reroute_flow": lambda p: f"Reroute flow {p['flow_id']} via {' → '.join(p['path'])}",
}


def _traffic(match: Row) -> str:
    """The traffic a QoS match selects: `flow sta1-video`, `video in the lecture hall`."""
    if match.get("flow_id"):
        return f"flow {match['flow_id']}"
    app, zone = match.get("app_class"), match.get("zone")
    if zone:
        return f"{app or 'traffic'} in the {zone.replace('_', ' ')}"
    return f"{app} traffic"


FINISHED = frozenset({"kept", "rolled_back", "rollback_failed"})  # a watch that decided


_ADR = re.compile(r"\s*\(ADR-\d+\)$")  # a verifier reason's decision record: not for the audience


KPI_WORDS = {field: label.split()[0] for label, field in KPIS} | {"jain": "fairness"}  # in reasons
_KPI_FIELD = re.compile(r"\b(?:" + "|".join(KPI_WORDS) + r")\b")


def why_not(verdict: Row) -> str:
    """A rejected verdict's first reason (without its action id and ADR reference, its KPI
    fields as words: latency_ms as latency), and how many more."""
    violations = verdict.get("violations") or []
    if not violations:
        return _predicted(verdict)  # rejected on its predicted KPIs: they say why
    first = _ADR.sub("", violations[0].split(": ", 1)[-1])
    first = _KPI_FIELD.sub(lambda m: KPI_WORDS[m.group(0)], first)
    more = len(violations) - 1
    return f"twin: {first}" + (f" (+{more} more {_plural(more, 'reason')})" if more else "")


def _predicted(verdict: Row) -> str:
    before, after = verdict.get("baseline") or {}, verdict.get("predicted") or {}
    if not before or not after or not any(d[f] for d in (before, after) for _, f in KPIS):
        return ""  # no flow affected (throughput, latency and loss all 0; fairness is not one)
    return (
        f"twin: latency {before['latency_ms']:.0f} → {after['latency_ms']:.0f} ms"
        f" · loss {before['loss_pct']:.1f}% → {after['loss_pct']:.1f}%"
    )


CAUSE_WORDS = {  # genai/rca/explainer.py Category
    "ap_down": "an access point down",
    "cochannel_interference": "co-channel interference",
    "congestion": "congestion",
    "bad_action": "a recent change",
    "other": "something else",
}
_STATION_LIST = re.compile(r"\bsta\d+(?:(?:,\s*(?:and\s+)?|\s+and\s+)sta\d+){2,}\b")  # 3+ names


@dataclass(frozen=True)
class RcaView:
    """A root-cause report, ready to read: causes as (cause, entity, confidence, evidence)."""

    summary: str
    causes: list[tuple[str, str, str, str]]
    suggestions: list[str]
    model: str
    error: str = ""


def rca_view(report: Row) -> RcaView:
    """POST /alerts/explain's report in plain words: categories as words, long station lists
    as a count, suggested actions with the twin's verdict."""
    if "error" in report:
        return RcaView("", [], [], "", error=report["error"])
    causes = [
        (
            CAUSE_WORDS.get(c["category"], c["category"].replace("_", " ")),
            c["entity"],
            f"{c['confidence']:.0%}",
            shorten(c["evidence"]),
        )
        for c in report["likely_causes"]
    ]
    suggestions = [
        f"{plain_action(s['action'])} · twin {verdict_word(s['verdict'])}"
        for s in report["suggested_actions"]
    ]
    return RcaView(shorten(report["summary"]), causes, suggestions, report.get("model", ""))


def shorten(text: str) -> str:
    """Station lists of three or more names as a count: `3 clients`. One or two names stay:
    they read fine and say who."""
    return _STATION_LIST.sub(lambda m: _clients(m.group(0).count("sta")), text)


EPISODE_GAP = timedelta(seconds=60)  # alerts on one entity closer than this are one episode


@dataclass(frozen=True)
class AlertGroup:
    """One episode of alerts on one entity: what the screen shows instead of every alert."""

    entity: str
    count: int
    first: str  # ISO times, as the API sends them
    last: str
    score: float  # the highest
    latest: Row  # the newest alert: what "Explain" sends to the root-cause explainer


def alert_groups(alerts: list[Row]) -> list[AlertGroup]:
    """Alerts (oldest first, as GET /alerts returns them) grouped into episodes per entity,
    newest episode first. A new episode starts after a minute without an alert on the entity."""
    episodes: list[list[Row]] = []
    open_: dict[str, list[Row]] = {}
    for a in alerts:
        run = open_.get(a["entity"])
        if run is None or _at(a) - _at(run[-1]) > EPISODE_GAP:
            run = open_[a["entity"]] = []
            episodes.append(run)
        run.append(a)
    groups = [
        AlertGroup(
            entity=run[0]["entity"],
            count=len(run),
            first=run[0]["ts"],
            last=run[-1]["ts"],
            score=max(a["score"] for a in run),
            latest=run[-1],
        )
        for run in episodes
    ]
    return sorted(groups, key=lambda g: g.last, reverse=True)


def _at(alert: Row) -> datetime:
    return datetime.fromisoformat(alert["ts"])


def verdict_word(verdict: Row) -> str:
    """The twin's verdict in a word, or the tool layer's refusal (invalid arguments)."""
    if "error" in verdict:
        return f"error: {verdict['error']}"
    return "accepted" if verdict["accepted"] else "rejected"


def kpi_series(points: Mapping[tuple[str, str], list[Row]], step_s: int = 10) -> list[Row]:
    """Long rows (class, kpi, t, value) from GET /metrics series keyed by (app class, KPI
    field): the mean over every flow of the class in each `step_s` step (probes are not in
    step with each other, so single points would zig-zag between flows)."""
    labels = {field: label for label, field in KPIS}
    rows = []
    for (app_class, field), series in points.items():
        steps: dict[datetime, list[float]] = {}
        for p in series:
            ts = datetime.fromisoformat(p["ts"])
            start = ts - timedelta(seconds=ts.second % step_s, microseconds=ts.microsecond)
            steps.setdefault(start, []).append(p["value"])
        rows += [
            {"class": app_class, "kpi": labels[field], "t": t.isoformat(), "value": fmean(v)}
            for t, v in sorted(steps.items())
        ]
    return rows
