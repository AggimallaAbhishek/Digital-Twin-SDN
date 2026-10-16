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
            label = f"{a['name']} · {a['util']:.0%} · {n}"  # the channel is drawn beside it
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


def latest_steer(actions: list[Row], aps: list[Row]) -> Row | None:
    """The arrow for the newest client steer still being watched: from its AP to the target
    (map_layers' AP rows), labelled with how many clients; None when there is none."""
    steers = [
        r for r in actions if r["status"] == "applied" and r["action"]["type"] == "steer_clients"
    ]
    if not steers:
        return None
    p = _newest(steers)["action"]["params"]
    where = {a["name"]: a for a in aps}
    if p["from_ap"] not in where or p["to_ap"] not in where:
        return None
    src, dst = where[p["from_ap"]], where[p["to_ap"]]
    return {
        "x": src["x"],
        "y": src["y"],
        "x2": dst["x"],
        "y2": dst["y"],
        "label": _clients(len(p["stations"])),
    }


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


def _newest(records: list[Row]) -> Row:
    """The record applied last (one never applied counts as oldest)."""
    return max(records, key=lambda r: r["applied_at"] or "")


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
    "steer_clients": lambda p: f"Move {_clients(len(p['stations']))} {p['from_ap']} → {p['to_ap']}",
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


@dataclass(frozen=True)
class Status:
    """The banner: how bad things are, what is wrong, and what the system is doing about it."""

    level: str  # waiting, calm, attention or critical
    headline: str
    doing: str  # empty when the system is doing nothing visible


def status(topology: Row | None, zones: list[Row], actions: list[Row]) -> Status:
    """The banner for the twin's state: the worst problem first (an AP down; congestion, with
    any clients without an AP added; clients without an AP; a busy AP), else all calm."""
    if topology is None:
        return Status("waiting", "Waiting for data from the network…", "")
    aps, stations = topology["aps"], topology["stations"]
    clients = {a["name"]: sum(s["ap"] == a["name"] for s in stations) for a in aps}
    down = [a for a in aps if not a["up"]]
    lost = sum(s["ap"] is None for s in stations)
    up = sorted((a for a in aps if a["up"]), key=lambda a: a["util"], reverse=True)
    congested = [a for a in up if band(a["util"]) == "congested"]
    doing = _doing(actions)
    if down:
        return Status("critical", f"{down[0]['name']} is down{_in(down[0], zones, '({})')}.", doing)
    no_ap = f"{_clients(lost)} {'has' if lost == 1 else 'have'} no access point"
    if congested:  # before clients without an AP: a steered client is unassociated briefly
        more = len(congested) - 1
        extra = f" and {more} more {_plural(more, 'AP')}" if more else ""
        line = _ap_line(congested[0], "congested", zones, clients) + extra
        return Status("critical", f"{line}{f' · {no_ap}' if lost else ''}.", doing)
    if lost:
        return Status("critical", f"{no_ap}.", doing)
    if up and band(up[0]["util"]) == "busy":
        return Status("attention", f"{_ap_line(up[0], 'busy', zones, clients)}.", doing)
    connected = len(stations) - lost
    return Status("calm", f"All access points are calm · {_clients(connected)} connected.", doing)


def _ap_line(ap: Row, state: str, zones: list[Row], clients: dict[str, int]) -> str:
    where = _in(ap, zones, "in the {}")
    return f"{ap['name']} is {state}{where} ({ap['util']:.0%}, {_clients(clients[ap['name']])})"


def _in(ap: Row, zones: list[Row], form: str) -> str:
    """` in the lecture hall` (the zone the AP stands in, in `form`), or nothing. Edges count
    as inside, as in twin/state/builder.py zone_of (which the dashboard may not import)."""
    x, y = ap["position"]
    for z in zones:
        if z["x"] <= x <= z["x2"] and z["y"] <= y <= z["y2"]:
            return " " + form.format(z["zone"])
    return ""


def _doing(actions: list[Row]) -> str:
    """What the system is visibly doing: a change being watched, else one waiting for the
    operator."""
    watched = [r for r in actions if r["status"] == "applied"]
    if watched:
        latest = _newest(watched)
        p = latest["action"]["params"]
        if latest["action"]["type"] == "steer_clients":
            return f"The system is moving {_clients(len(p['stations']))} to {p['to_ap']}."
        return f"The system is checking: {plain_action(latest['action'])}."
    return "A change is waiting for you." if waiting_steps(actions) else ""


@dataclass(frozen=True)
class Tile:
    """One big number under the banner."""

    value: str
    label: str
    tone: str  # calm, critical, action, good or warn: the colour


FINISHED = {  # final status → (tile value, label, tone)
    "kept": ("✓", "last change kept", "good"),
    "rolled_back": ("↺", "last change rolled back", "warn"),
    "rollback_failed": ("✕", "last rollback failed", "critical"),
}


def tiles(topology: Row | None, actions: list[Row]) -> list[Tile]:
    """APs congested, clients without an AP, changes waiting for the operator, and how the
    last finished change ended."""
    waiting = len(waiting_steps(actions))
    finished = [r for r in actions if r["status"] in FINISHED]
    last = (
        Tile(*FINISHED[_newest(finished)["status"]])
        if finished
        else Tile("—", "no change yet", "calm")
    )
    queue = Tile(str(waiting), "waiting for you", "action" if waiting else "calm")
    if topology is None:
        return [
            Tile("—", "APs congested", "calm"),
            Tile("—", "clients without an AP", "calm"),
            queue,
            last,
        ]
    congested = sum(a["up"] and band(a["util"]) == "congested" for a in topology["aps"])
    lost = sum(s["ap"] is None for s in topology["stations"])
    return [
        Tile(str(congested), f"{_plural(congested, 'AP')} congested", _alarm(congested)),
        Tile(str(lost), f"{_plural(lost, 'client')} without an AP", _alarm(lost)),
        queue,
        last,
    ]


def _alarm(n: int) -> str:
    return "critical" if n else "calm"


@dataclass(frozen=True)
class Item:
    """One step of the "What is happening" timeline."""

    kind: str  # waiting, applied, checked, outcome or detected
    at: str  # ISO time, for ordering and display
    title: str
    detail: str
    badge: str
    tone: str  # as Tile.tone
    action_id: str | None = None
    next_step: str | None = None  # approve or apply, for a waiting change
    group: AlertGroup | None = None  # for a detected episode: what "Explain" explains


OUTCOMES = {  # final status → (badge, tone)
    "kept": ("✓ kept", "good"),
    "rolled_back": ("↺ rolled back", "warn"),
    "rollback_failed": ("✕ rollback failed", "critical"),
    "failed": ("✕ could not apply", "critical"),
}


def timeline(actions: list[Row], alerts: list[Row], watch: timedelta, limit: int = 8) -> list[Item]:
    """The story newest first: every change waiting for the operator on top, then the twin's
    checks, applied changes and their outcomes, and the alert episodes: `limit` items in all,
    but never fewer than the waiting changes (each needs its buttons)."""
    waiting = waiting_steps(actions)
    pinned, items = [], []
    for r in actions:
        title = plain_action(r["action"])
        if r["action_id"] in waiting:
            pinned.append(_waiting(r, title, waiting[r["action_id"]]))
            continue
        items.append(_checked(r, title))
        if r["applied_at"] and r["status"] == "applied":
            items.append(
                Item("applied", r["applied_at"], title, "", f"watching {watch.seconds} s", "action")
            )
        elif r["status"] in OUTCOMES:
            at = r["applied_at"] or r["action"]["created_at"]
            done = (datetime.fromisoformat(at) + watch).isoformat()
            items.append(Item("outcome", done, title, _measured(r), *OUTCOMES[r["status"]]))
    items += [
        Item(
            "detected",
            g.last,
            f"{g.entity} looks unusual",
            "",
            _alerts(g.count),
            "critical",
            group=g,
        )
        for g in alert_groups(alerts)
    ]
    items.sort(key=lambda i: i.at, reverse=True)
    pinned.sort(key=lambda i: i.at, reverse=True)
    return pinned + items[: max(limit - len(pinned), 0)]


def _waiting(r: Row, title: str, step: str) -> Item:
    v = r["verdict"]
    parts = (r["action"].get("source", ""), f"{v['impact']} impact", _predicted(v))
    detail = " · ".join(p for p in parts if p)
    return Item(
        "waiting",
        r["action"]["created_at"],
        title,
        detail,
        "waiting for you",
        "action",
        action_id=r["action_id"],
        next_step=step,
    )


def _checked(r: Row, title: str) -> Item:
    v = r["verdict"]
    if r["status"] == "denied":
        badge, tone = "denied by the operator", "calm"
    elif v.get("accepted"):
        badge, tone = "accepted", "calm"
    else:
        badge, tone = "✕ rejected", "warn"
    return Item(
        "checked",
        r["action"]["created_at"],
        title,
        _predicted(v) if v.get("accepted") or r["status"] == "denied" else _why_not(v),
        badge,
        tone,
        action_id=r["action_id"],
    )


_ADR = re.compile(r"\s*\(ADR-\d+\)$")  # a verifier reason's decision record: not for the audience


def _why_not(verdict: Row) -> str:
    """A rejected verdict's first reason (without its action id and ADR reference), and how
    many more."""
    violations = verdict.get("violations") or []
    if not violations:
        return _predicted(verdict)  # rejected on its predicted KPIs: they say why
    first = _ADR.sub("", violations[0].split(": ", 1)[-1])
    more = len(violations) - 1
    return f"twin: {first}" + (f" (+{more} more {_plural(more, 'reason')})" if more else "")


def _predicted(verdict: Row) -> str:
    before, after = verdict.get("baseline") or {}, verdict.get("predicted") or {}
    if not before or not after:
        return ""
    return (
        f"twin: latency {before['latency_ms']:.0f} → {after['latency_ms']:.0f} ms"
        f" · loss {before['loss_pct']:.1f}% → {after['loss_pct']:.1f}%"
    )


def _measured(r: Row) -> str:
    measured, predicted = r.get("measured"), r["verdict"].get("predicted")
    if not measured or not predicted:
        return ""
    return (
        f"latency: twin {predicted['latency_ms']:.0f} ms · measured {measured['latency_ms']:.0f} ms"
    )


def _alerts(n: int) -> str:
    return f"{n} {_plural(n, 'alert')}"


CAUSE_WORDS = {  # genai/rca/explainer.py Category
    "ap_down": "an access point down",
    "cochannel_interference": "co-channel interference",
    "congestion": "congestion",
    "bad_action": "a recent change",
    "other": "something else",
}
_STATION_LIST = re.compile(r"\bsta\d+(?:,\s*(?:and\s+)?sta\d+){2,}\b")  # three or more names


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
            _short(c["evidence"]),
        )
        for c in report["likely_causes"]
    ]
    suggestions = [
        f"{plain_action(s['action'])} · twin {verdict_word(s['verdict'])}"
        for s in report["suggested_actions"]
    ]
    return RcaView(_short(report["summary"]), causes, suggestions, report.get("model", ""))


def _short(text: str) -> str:
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


def twin_vs_live(actions: list[Row]) -> list[Row]:
    """Long rows (action, kpi, source, value): before, twin predicted and measured, for every
    action whose watch has measured the network (the ledger's `measured`)."""
    rows = []
    for r in actions:
        measured = r.get("measured")
        if not measured:
            continue
        verdict = r["verdict"]
        for label, field in KPIS:
            for source, values in (
                ("before", verdict["baseline"]),
                ("twin predicted", verdict["predicted"]),
                ("measured", measured),
            ):
                rows.append(
                    {
                        "action": r["action_id"],
                        "what": plain_action(r["action"]),
                        "outcome": r["status"],
                        "kpi": label,
                        "source": source,
                        "value": values[field],
                    }
                )
    return rows
