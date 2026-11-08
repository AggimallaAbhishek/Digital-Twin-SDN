"""Blueprint + Sorbet panels (docs/superpowers/specs/2026-11-09-dashboard-blueprint-sorbet-
design.md §4): what the redesigned dashboard's panels show, from the API's JSON and the demo's
run file (logs/demo/run.json). Pure functions, no Streamlit (tests/unit/test_dashboard_panels.py).

The older view logic (status, timeline, wording, safety of API text) stays in views.py and is
reused here.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from dashboard.svg import Move
from dashboard.theme import ZONE_TOKENS
from dashboard.views import FINISHED, alert_groups, band, plain_action, waiting_steps, why_not

Row = dict[str, Any]  # Any: JSON values
RANGE = chr(0x2013)  # an en dash, for time ranges such as 0:00 to 2:00


@dataclass(frozen=True)
class Live:
    """One refresh of the API's live reads: the twin state (None before the first telemetry),
    the action ledger and the recent alerts."""

    topology: Row | None
    actions: Sequence[Row]
    alerts: Sequence[Row]


# ---------------------------------------------------------------- the one input box

_QUESTION_WORDS = frozenset(
    [
        "why",
        "what",
        "how",
        "which",
        "who",
        "when",
        "where",
        "is",
        "are",
        "does",
        "do",
        "did",
        "can",
        "could",
        "should",
        "will",
        "would",
        "explain",
        "show",
        "list",
        "tell",
    ]
)


def route(text: str) -> str:
    """Where the copilot box sends `text`: "ask" (the copilot chat) for a question, by its "?"
    or its first word; "intent" (the intent engine) for anything else (design decision 4)."""
    words = text.strip().lower().split()
    if text.strip().endswith("?") or (words and words[0] in _QUESTION_WORDS):
        return "ask"
    return "intent"


# ---------------------------------------------------------------- the demo clock


@dataclass(frozen=True)
class DemoClock:
    """The running demo: its scenario's title, when it started and how far into it we are."""

    title: str
    start: datetime
    elapsed_s: int
    duration_s: int
    ended: bool

    def text(self) -> tuple[str, str]:
        """("03:40", "10:00"): elapsed and total, as the header shows them."""
        return _mmss(self.elapsed_s), _mmss(self.duration_s)


def _mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def demo_clock(run: Row | None, now: datetime) -> DemoClock | None:
    """The demo clock from logs/demo/run.json (written by `make demo`); None without a run or
    when the file lacks what the clock needs."""
    if not run or "started_at" not in run or "duration_s" not in run:
        return None
    start = datetime.fromisoformat(run["started_at"])
    duration = int(run["duration_s"])
    end = datetime.fromisoformat(run["finished_at"]) if run.get("finished_at") else now
    elapsed = int((min(end, now) - start).total_seconds())
    ended = bool(run.get("finished_at")) or elapsed >= duration
    return DemoClock(
        str(run.get("title") or run.get("scenario", "")),
        start,
        max(0, min(elapsed, duration)),
        duration,
        ended,
    )


def clock_label(at: str, start: datetime | None) -> str:
    """An event's time: on the demo clock ("03:30") during a demo, else the local wall clock."""
    when = datetime.fromisoformat(at)
    if start is None:
        return when.astimezone().strftime("%H:%M:%S")
    return _mmss((when - start).total_seconds())


# ---------------------------------------------------------------- the story strip


@dataclass(frozen=True)
class Step:
    """One step of the story strip: done (mint), now (coral) or next (dashed)."""

    label: str
    sub: str
    state: str


def _mss(seconds: float) -> str:
    """m:ss, as the story strip writes its times (0:00, 3:30)."""
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def story_steps(
    story: Sequence[Row],
    clock: DemoClock,
    live: Live,
    watch: timedelta,
    congested_s: float | None = None,
) -> list[Step]:
    """The story strip (design §4.2): each step is reached by its trigger (the demo clock, the
    first congestion seen, the first change proposed, applied, or decided), events from before
    the run do not count; the latest step reached is "now", the ones before it done.
    `congested_s`: when an AP was first seen congested in this run (the dashboard remembers
    it; the twin state only knows now). Anomaly alerts are not congestion: the detector also
    flags start-up transients (live demo 2026-11-09)."""
    reached = [_reached(s, clock, live, watch, congested_s) for s in story]
    later: float | None = None  # the earliest time a later step was reached
    for i in reversed(range(len(reached))):
        at = reached[i]
        if at is None:
            continue
        if later is not None and at > later:
            reached[i] = None  # first seen after a later step: its start was missed
        else:
            later = at
    current = max((i for i, r in enumerate(reached) if r is not None), default=-1)
    steps = []
    for i, (spec, at) in enumerate(zip(story, reached, strict=True)):
        if i > current:
            steps.append(Step(spec["label"], _plan(spec), "next"))
            continue
        state = "now" if i == current and not clock.ended else "done"
        if spec["trigger"] == "clock" and "to_s" in spec:
            when = _window(spec)
        elif at is not None:
            when = _mss(at)
        else:  # passed over: a later step happened first
            when = f"about {_mss(spec['from_s'])}"
        steps.append(
            Step(spec["label"], f"{when}, {'happening now' if state == 'now' else 'done'}", state)
        )
    return steps


def _window(spec: Row) -> str:
    return f"{_mss(spec['from_s'])}{RANGE}{_mss(spec['to_s'])}"


def _plan(spec: Row) -> str:
    """What an upcoming step says: its planned window, or about when it is due."""
    return _window(spec) if "to_s" in spec else f"about {_mss(spec['from_s'])}"


def congested_now(topology: Row | None) -> bool:
    """True when an AP that is up is congested in the twin state."""
    return topology is not None and any(
        a["up"] and band(a["util"]) == "congested" for a in topology["aps"]
    )


def _reached(
    spec: Row, clock: DemoClock, live: Live, watch: timedelta, congested_s: float | None
) -> float | None:
    """Seconds into the run at which `spec`'s trigger happened; None if it has not (yet)."""
    trigger, start, actions = spec["trigger"], clock.start, live.actions
    if trigger == "clock":
        return float(spec["from_s"]) if clock.elapsed_s >= spec["from_s"] else None
    if trigger == "congested":
        if congested_s is not None:
            return congested_s
        return float(clock.elapsed_s) if congested_now(live.topology) else None
    if trigger == "proposed":
        return min(_since(start, (r["action"]["created_at"] for r in actions)), default=None)
    if trigger == "applied":
        applied = (r["applied_at"] for r in actions if r["applied_at"])
        return min(_since(start, applied), default=None)
    if trigger == "outcome":  # a change is decided when its watch ends
        decided = (
            (datetime.fromisoformat(r["applied_at"]) + watch).isoformat()
            for r in actions
            if r["status"] in FINISHED and r["applied_at"]
        )
        return min(_since(start, decided), default=None)
    raise ValueError(f"unknown story trigger {trigger!r}")


TRIGGERS = frozenset({"clock", "congested", "proposed", "applied", "outcome"})
_STEP_KEYS = frozenset({"label", "trigger", "from_s", "to_s"})


def load_stories(raw: Row) -> dict[str, list[Row]]:
    """config/dashboard.yaml's stories, validated (C-3): ValueError names the bad field."""
    stories = raw.get("stories")
    if not isinstance(stories, dict):
        raise ValueError("config/dashboard.yaml: stories must be a mapping of scenario -> steps")
    for scenario, steps in stories.items():
        for i, step in enumerate(steps):
            where = f"stories.{scenario}[{i}]"
            unknown = set(step) - _STEP_KEYS
            if unknown:
                raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
            if not isinstance(step.get("label"), str) or not step["label"]:
                raise ValueError(f"{where}: label must be a non-empty text")
            if step.get("trigger") not in TRIGGERS:
                raise ValueError(f"{where}: trigger must be one of {sorted(TRIGGERS)}")
            if not isinstance(step.get("from_s"), int) or step["from_s"] < 0:
                raise ValueError(f"{where}: from_s must be whole seconds >= 0")
            if "to_s" in step and (
                not isinstance(step["to_s"], int) or step["to_s"] <= step["from_s"]
            ):
                raise ValueError(f"{where}: to_s must be whole seconds after from_s")
    return {str(k): list(v) for k, v in stories.items()}


# ---------------------------------------------------------------- status card, tiles, AP rows


@dataclass(frozen=True)
class Hero:
    """The status card: its colour token, icon, small line and headline."""

    tone: str
    icon: str
    eyebrow: str
    headline: str


HERO_LOOK = {  # level -> (colour token, icon); never colour alone
    "critical": ("coral", "⚠"),
    "attention": ("yellow", "!"),
    "calm": ("mint", "✓"),
    "waiting": ("white", "…"),
}


def hero(live: Live, zones: Sequence[Row], start: datetime | None) -> Hero:
    """The worst problem first, in plain words: an AP down, the most loaded congested AP,
    clients without an AP, a busy AP, else all calm. The small line says when the anomaly
    detector flagged that AP (or when the twin saw it)."""
    topo = live.topology
    if topo is None:
        return Hero(*HERO_LOOK["waiting"], "No twin state yet", "Waiting for data from the network")
    up = sorted((a for a in topo["aps"] if a["up"]), key=lambda a: a["util"], reverse=True)
    down = [a for a in topo["aps"] if not a["up"]]
    lost = sum(s["ap"] is None for s in topo["stations"])
    subject: Row | None = None
    if down:
        level, subject, line = "critical", down[0], "{} is down{}"
    elif up and band(up[0]["util"]) == "congested":
        level, subject, line = "critical", up[0], "{} is congested{}"
    elif lost:
        level, line = (
            "critical",
            f"{lost} {'client has' if lost == 1 else 'clients have'} no access point",
        )
    elif up and band(up[0]["util"]) == "busy":
        level, subject, line = "attention", up[0], "{} is busy{}"
    else:
        level, line = "calm", "All access points are calm"
    if subject is not None:
        zone = _zone_name(subject, zones)
        line = line.format(subject["name"], f" in the {zone}" if zone else "")
    tone, icon = HERO_LOOK[level]
    return Hero(tone, icon, _when(level, subject, live.alerts, topo, start), line)


def _when(
    level: str, subject: Row | None, alerts: Sequence[Row], topo: Row, start: datetime | None
) -> str:
    if level == "calm":
        return f"Status at {clock_label(topo['ts'], start)}"
    flagged = [g for g in alert_groups(list(alerts)) if subject and g.entity == subject["name"]]
    if flagged:
        return f"Anomaly detected at {clock_label(flagged[0].first, start)}"
    return f"Seen at {clock_label(topo['ts'], start)}"


def _zone_name(ap: Row, zones: Sequence[Row]) -> str:
    """The zone an AP stands in (edges count as inside, like the twin's zone_of), or ""."""
    x, y = ap["position"]
    for z in zones:
        if z["x"] <= x <= z["x2"] and z["y"] <= y <= z["y2"]:
            return str(z["zone"])
    return ""


@dataclass(frozen=True)
class Focus:
    """The AP the three big tiles describe: the most loaded one that is up."""

    name: str
    clients: int
    util: float
    loss_pct: float | None  # the mean loss of its clients' flows; None without flows


def focus_ap(topology: Row | None) -> Focus | None:
    """The most loaded AP that is up, with its clients and their flows' mean packet loss."""
    if topology is None:
        return None
    up = [a for a in topology["aps"] if a["up"]]
    if not up:
        return None
    ap = max(up, key=lambda a: a["util"])
    mine = {s["name"] for s in topology["stations"] if s["ap"] == ap["name"]}
    losses = [f["loss_pct"] for f in topology.get("flows", []) if f["sta"] in mine]
    loss = sum(losses) / len(losses) if losses else None
    return Focus(ap["name"], len(mine), ap["util"], loss)


@dataclass(frozen=True)
class ApRow:
    """One row of the Access points card."""

    name: str
    chip: str  # colour token: the zone's sorbet colour, coral when congested, grey when down
    what: str
    pct: str
    width: int  # the load bar, 0 to 100
    hot: bool  # congested: a red hatched bar and a red percentage


def ap_rows(topology: Row, zones: Sequence[Row]) -> list[ApRow]:
    """Every AP: its zone, channel and clients, and its load as a bar."""
    clients = {a["name"]: 0 for a in topology["aps"]}
    for s in topology["stations"]:
        if s["ap"] in clients:
            clients[s["ap"]] += 1
    rows = []
    for a in topology["aps"]:
        zone = _zone_name(a, zones)
        where = f"{zone[:1].upper()}{zone[1:]}, " if zone else ""
        if not a["up"]:
            rows.append(
                ApRow(a["name"], "grey", f"{where}channel {a['channel']}, off", "off", 0, False)
            )
            continue
        n = clients[a["name"]]
        hot = band(a["util"]) == "congested"
        chip = "coral" if hot else ZONE_TOKENS.get(zone, "white")
        what = f"{where}channel {a['channel']}, {n} {'client' if n == 1 else 'clients'}"
        rows.append(
            ApRow(a["name"], chip, what, f"{a['util']:.0%}", min(100, round(a["util"] * 100)), hot)
        )
    return rows


# ---------------------------------------------------------------- event timeline

OUTCOME_EVENTS = {  # final status -> (chip colour, title)
    "kept": ("mint", "Change kept"),
    "rolled_back": ("coral", "Change rolled back"),
    "rollback_failed": ("coral", "Rollback failed"),
    "failed": ("coral", "Could not apply"),
}


@dataclass(frozen=True)
class Event:
    """One row of the Event timeline: its time chip (text and colour), title and detail."""

    time: str
    tone: str
    title: str
    detail: str


def source_word(source: str) -> str:
    """Who proposed a change, in a word: the optimiser, the AI copilot or an operator."""
    if source.startswith("optimizer"):
        return "Optimiser"
    if source.startswith("llm"):
        return "AI copilot"
    return "Operator"


def event_rows(live: Live, watch: timedelta, start: datetime | None, limit: int = 6) -> list[Event]:
    """The run's story as events in reading order (oldest first, the newest `limit` kept):
    alert episodes, changes proposed or rejected by the twin, denied, applied, and how each
    watch ended."""
    timed: list[tuple[datetime, Event]] = []

    def add(at: str, tone: str, title: str, detail: str) -> None:
        timed.append(
            (datetime.fromisoformat(at), Event(clock_label(at, start), tone, title, detail))
        )

    for g in reversed(alert_groups(list(live.alerts))):  # oldest episode first
        add(
            g.first,
            "coral",
            f"{g.entity} looks unusual",
            f"{g.count} anomaly {'alert' if g.count == 1 else 'alerts'}",
        )
    for r in live.actions:
        what, v, created = plain_action(r["action"]), r["verdict"], r["action"]["created_at"]
        if not v.get("accepted"):
            add(created, "coral", "Twin rejects a change", f"{what}; {why_not(v)}")
            continue
        add(
            created,
            "lavender",
            f"{source_word(r['action'].get('source', ''))} proposes a change",
            _with_prediction(what, v),
        )
        if r["status"] == "denied":
            add(created, "white", "Operator denied it", what)
        if r["applied_at"]:
            add(
                r["applied_at"],
                "yellow",
                "Applying the change",
                f"{what}, watching for {watch.seconds} s",
            )
        if r["status"] in OUTCOME_EVENTS:
            at = r["applied_at"] or created
            done = (datetime.fromisoformat(at) + watch).isoformat()
            add(done, *OUTCOME_EVENTS[r["status"]], _latency_check(r))
    timed.sort(key=lambda t: t[0])  # stable: a proposal stays before its denial
    return [e for _, e in timed[-limit:]]


def _with_prediction(what: str, verdict: Row) -> str:
    predicted = verdict.get("predicted")
    if not predicted:
        return what
    latency, loss = predicted["latency_ms"], predicted["loss_pct"]
    return f"{what}; twin predicts {latency:.0f} ms and {loss:.1f}% loss"


def _latency_check(record: Row) -> str:
    measured, predicted = record.get("measured"), record["verdict"].get("predicted")
    if not measured or not predicted:
        return ""
    return (
        f"Latency: twin {predicted['latency_ms']:.0f} ms, measured {measured['latency_ms']:.0f} ms"
    )


# ---------------------------------------------------------------- proposal card

RESULT_FOR = timedelta(minutes=10)  # how long a finished change stays on the proposal card
RESULT_WORDS = {
    "kept": "✓ Kept",
    "rolled_back": "↺ Rolled back",
    "rollback_failed": "✕ Rollback failed",
    "failed": "✕ Could not apply",
}


@dataclass(frozen=True)
class Proposal:
    """The proposal card: a change waiting for the operator, being watched, or its result."""

    kind: str  # waiting, watching or result
    eyebrow: str
    title: str
    latency: tuple[float, float] | None  # (twin predicted, before), ms
    loss: tuple[float, float] | None  # (twin predicted, before), %
    accepted: bool
    note: str
    action_id: str
    next_step: str | None  # approve or apply, for a waiting change
    progress: float  # how far the watch has run, 0 to 1


def proposal_view(
    live: Live, now: datetime, watch: timedelta, start: datetime | None
) -> Proposal | None:
    """The change that matters most now: one waiting for the operator, else the one being
    watched, else the newest result (kept, rolled back, rejected) of the last 10 minutes."""
    actions = live.actions
    waiting = waiting_steps(list(actions))
    if waiting:
        r = max(
            (a for a in actions if a["action_id"] in waiting),
            key=lambda a: a["action"]["created_at"],
        )
        source = source_word(r["action"].get("source", ""))
        eyebrow = f"{source} proposal" if source != "AI copilot" else "AI proposal"
        return replace(_proposal(r, "waiting", eyebrow), next_step=waiting[r["action_id"]])
    watched = [a for a in actions if a["status"] == "applied" and a["applied_at"]]
    if watched:
        r = max(watched, key=lambda a: a["applied_at"])
        applied = datetime.fromisoformat(r["applied_at"])
        progress = min(1.0, max(0.0, (now - applied) / watch))
        eyebrow = (
            f"Applied at {clock_label(r['applied_at'], start)} · watching for {watch.seconds} s"
        )
        return replace(_proposal(r, "watching", eyebrow), progress=progress)
    results = [
        (_decided(a, watch), a)
        for a in actions
        if a["status"] in RESULT_WORDS or a["status"] == "rejected"
    ]
    if not results:
        return None
    at, r = max(results, key=lambda t: t[0])
    if now - at > RESULT_FOR:
        return None
    source = source_word(r["action"].get("source", ""))
    return replace(_proposal(r, "result", f"{source} change"), note=_result_note(r))


def _decided(record: Row, watch: timedelta) -> datetime:
    """When a change's fate was known: the end of its watch, or its twin check if rejected."""
    if record["status"] != "rejected" and record["applied_at"]:
        return datetime.fromisoformat(record["applied_at"]) + watch
    return datetime.fromisoformat(record["action"]["created_at"])


def _result_note(record: Row) -> str:
    if record["status"] == "rejected":
        return f"✕ Twin rejected: {why_not(record['verdict']).removeprefix('twin: ')}"
    note = RESULT_WORDS[record["status"]]
    measured = record.get("measured")
    if measured:
        note += (
            f" · measured latency {measured['latency_ms']:.0f} ms, loss {measured['loss_pct']:.1f}%"
        )
    return note


def _proposal(r: Row, kind: str, eyebrow: str) -> Proposal:
    """The card for record `r`, with its twin prediction; no step, progress or note yet."""
    v = r["verdict"]
    before, after = v.get("baseline") or {}, v.get("predicted") or {}
    both = bool(before) and bool(after)
    return Proposal(
        kind=kind,
        eyebrow=eyebrow,
        title=plain_action(r["action"]),
        latency=(after["latency_ms"], before["latency_ms"]) if both else None,
        loss=(after["loss_pct"], before["loss_pct"]) if both else None,
        accepted=bool(v.get("accepted")),
        note="",
        action_id=r["action_id"],
        next_step=None,
        progress=0.0,
    )


# ---------------------------------------------------------------- the map's move arrow


def map_move(actions: Sequence[Row]) -> Move | None:
    """The steer to draw on the map: the newest one being watched ("moving"), else the newest
    one waiting for the operator ("proposed"); None when there is neither."""
    steers = [a for a in actions if a["action"]["type"] == "steer_clients"]
    watched = [a for a in steers if a["status"] == "applied" and a["applied_at"]]
    if watched:
        return _move(max(watched, key=lambda a: a["applied_at"]), "moving")
    waiting = waiting_steps(list(steers))
    pending = [a for a in steers if a["action_id"] in waiting]
    if pending:
        return _move(max(pending, key=lambda a: a["action"]["created_at"]), "proposed")
    return None


def _move(record: Row, state: str) -> Move:
    p = record["action"]["params"]
    return Move(p["from_ap"], p["to_ap"], tuple(p["stations"]), state)


# ---------------------------------------------------------------- an intent's reply


@dataclass(frozen=True)
class IntentView:
    """The copilot's reply to an intent: what it would change and the twin's check."""

    text: str
    ok: bool
    check: str  # "Twin check passed …" or "Twin refused: …"; "" with nothing to check
    applicable: tuple[str, ...]  # the action ids "Create and apply policy" applies


def intent_view(result: Row) -> IntentView:
    """POST /intents' result in plain words. The set applies only if the twin accepted all of
    it (the twin verified the set together)."""
    if result.get("error"):
        return IntentView(str(result["error"]), False, "", ())
    actions = result["actions"]
    if not actions:
        return IntentView("Nothing to change: the network already does that.", True, "", ())
    n = len(actions)
    changes = f"{n} change{'' if n == 1 else 's'}"
    text = f"I can make {changes}: " + "; ".join(plain_action(a) for a in actions) + "."
    verdicts = [result["verdicts"].get(a["action_id"], {}) for a in actions]
    refused = [v for v in verdicts if not v.get("accepted")]
    if refused:
        v = refused[0]
        why = v["error"] if "error" in v else why_not(v).removeprefix("twin: ")
        return IntentView(text, False, f"Twin refused: {why}", ())
    return IntentView(
        text, True, f"Twin check passed for {changes}", tuple(a["action_id"] for a in actions)
    )


def _since(start: datetime, times: Iterable[str]) -> list[float]:
    """Seconds since `start` of the ISO `times` at or after it (earlier runs do not count)."""
    out = []
    for t in times:
        s = (datetime.fromisoformat(t) - start).total_seconds()
        if s >= 0:
            out.append(s)
    return out
