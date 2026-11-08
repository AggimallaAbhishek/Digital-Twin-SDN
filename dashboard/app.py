"""P6.1 operator dashboard (Streamlit), "Blueprint + Sorbet" design
(docs/superpowers/specs/2026-11-09-dashboard-blueprint-sorbet-design.md; the image is
`frontend design images/Final — Blueprint + Sorbet@2x.png`).

    make dashboard     # streamlit on http://127.0.0.1:8501 (needs `make api`)

One live screen with six pages (Overview, Network map, Digital twin, AI copilot, Policies,
History and logs). It talks to the P3.6 API over HTTP only (dashboard/client.py); the operator
token stays in this server process (OPERATOR_TOKEN in .env) and never reaches the browser. Every
string from the API is escaped before it goes into HTML or SVG: reasons, answers and reports can
be written by the LLM (rule L-6). What each panel shows is decided in dashboard/panels.py and
dashboard/views.py (pure, unit-tested); this file lays it out.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
import yaml

from dashboard.client import ApiClient, ApiError
from dashboard.panels import (
    DemoClock,
    Live,
    Proposal,
    ap_rows,
    clock_label,
    congested_now,
    demo_clock,
    event_rows,
    focus_ap,
    hero,
    intent_view,
    load_stories,
    map_move,
    proposal_view,
    route,
    source_word,
    story_steps,
)
from dashboard.svg import floor_plan_svg, twin_bars_svg
from dashboard.theme import CSS, INDIGO, LAVENDER, MUTED, NAVY, RED, WHITE
from dashboard.views import (
    CONGESTED,
    KPIS,
    AlertGroup,
    alert_groups,
    kpi_series,
    map_layers,
    md_literal,
    plain_action,
    rca_view,
    rich_html,
    safe_html,
    shorten,
    verdict_word,
    why_not,
)

ROOT = Path(__file__).resolve().parents[1]
API_URL = os.getenv("DASHBOARD_API_URL", "http://127.0.0.1:8000")
OPERATOR = os.getenv("OPERATOR_NAME", "operator")
RUN_FILE = ROOT / "logs" / "demo" / "run.json"  # written by `make demo` (experiments/demo.py)
REFRESH = "5s"  # the live panels
CHART_REFRESH = "15s"  # the Altair charts: up to 9 series queries a refresh
READ_TTL_S = 3  # the panels of one refresh share one read of /topology, /actions, /alerts
ALERTS_S = 600  # alerts this recent make the episodes
WINDOW_S = 300  # the charts' window ("last 5 minutes")
SHOWN_CHATS = 2  # copilot exchanges on the Overview card (all of them on the AI copilot page)
TABS = ("Overview", "Network map", "Digital twin", "AI copilot", "Policies", "History and logs")
CLASSES = {"video": "#7B4FC4", "web": "#C23B7A", "bulk": "#4F6B12"}  # traffic classes (charts)
WIFI_ICON = (
    f'<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="{NAVY}" '
    'stroke-width="2.6" stroke-linecap="round" aria-hidden="true">'
    '<path d="M2.5 9a14 14 0 0 1 19 0"/>'
    '<path d="M6 12.6a9 9 0 0 1 12 0"/><path d="M9.5 16.2a4 4 0 0 1 5 0"/>'
    f'<circle cx="12" cy="19.5" r="1.4" fill="{NAVY}" stroke="none"/></svg>'
)


# ---------------------------------------------------------------- reads


@st.cache_resource
def client() -> ApiClient:
    """The API client; the operator token stays in this server process."""
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


@st.cache_data
def stories() -> dict[str, list[dict[str, Any]]]:
    """The demo stories of the story strip (config/dashboard.yaml)."""
    return load_stories(config("dashboard.yaml"))


def run_file() -> dict[str, Any] | None:
    """The demo playing now (logs/demo/run.json), or None: no demo, or a file being written."""
    try:
        run: dict[str, Any] = json.loads(RUN_FILE.read_text())
    except (OSError, ValueError):
        return None
    return run


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
    return datetime.now(UTC)


def html(markup: str, where: Any = st) -> None:  # Any: st or a container
    """Markup built here (every API string in it already escaped)."""
    where.markdown(markup, unsafe_allow_html=True)


def start_of(clock: DemoClock | None) -> datetime | None:
    return clock.start if clock else None


# ---------------------------------------------------------------- header and story strip


@st.fragment(run_every=REFRESH)
def header() -> None:
    """The four header cells: the name, the scenario, the demo clock and the live status."""
    snap, clock = live(), demo_clock(run_file(), now())
    if clock is not None and snap is not None:
        congested_since(clock, snap)  # every page shows the header: the onset is never missed
    if clock is None:
        scenario, clock_html = "No demo running", "—"
    else:
        scenario = clock.title
        elapsed, total = clock.text()
        clock_html = f"{elapsed} <small>/ {total}{' · ended' if clock.ended else ''}</small>"
    if snap is None:
        state, words = "down", "API not answering · reconnecting by itself"
    elif snap.topology is None:
        state, words = "wait", "API up, waiting for telemetry"
    else:
        lag = max(0.0, (now() - datetime.fromisoformat(snap.topology["ts"])).total_seconds())
        state, words = "ok", f"Twin in sync with the network · {lag:.0f} s behind live"
    conn = f'<div class="conn {state}"><i></i><span>{words}</span></div>'
    pill = "Live demo" if clock and not clock.ended else "Live"
    html(
        '<div class="hdr">'
        f'<div class="brand"><div class="logo">{WIFI_ICON}</div><div><div class="name">'
        'Campus Wi-Fi Twin</div><div class="sub">GenAI-driven digital twin for intelligent SDN '
        "Wi-Fi</div></div></div>"
        f'<div><div class="k">Scenario</div><div class="v">{safe_html(scenario)}</div></div>'
        f'<div><div class="k">Demo clock</div><div class="clock">{clock_html}</div></div>'
        f'<div><span class="live-pill"><i></i>{pill}</span>{conn}</div>'
        "</div>"
    )


@st.cache_resource
def congestion_memo() -> dict[str, float]:
    """When this server first saw an AP congested, per run (keyed by the run's start), in
    seconds into the run: the twin state only knows now. Shared by every browser session."""
    return {}


def congested_since(clock: DemoClock, snap: Live) -> float | None:
    """The run's congestion onset as this server saw it (recorded on first sight)."""
    memo, key = congestion_memo(), clock.start.isoformat()
    if key not in memo and congested_now(snap.topology):
        memo[key] = float(clock.elapsed_s)
    return memo.get(key)


def story_strip(snap: Live, clock: DemoClock | None) -> None:
    """The six steps of the demo's story (only while a demo with a story plays)."""
    story = stories().get(clock_scenario(), []) if clock else []
    if not story or clock is None:
        return
    steps = story_steps(story, clock, snap, watch(), congested_since(clock, snap))
    html(
        '<div class="steps">'
        + "".join(
            f'<div class="step {s.state}"><b>{i} {safe_html(s.label)}</b>'
            f"<span>{safe_html(s.sub)}</span></div>"
            for i, s in enumerate(steps, start=1)
        )
        + "</div>"
    )


def clock_scenario() -> str:
    run = run_file()
    return str(run.get("scenario", "")) if run else ""


def hero_row(snap: Live, start: datetime | None) -> None:
    """The status card and the three big numbers of the most loaded AP."""
    zones = campus()
    card = hero(snap, zones, start)
    focus = focus_ap(snap.topology)
    if focus is None:
        tiles = [("—", "Clients"), ("—", "Load"), ("—", "Packet loss")]
    else:
        loss = "—" if focus.loss_pct is None else f"{focus.loss_pct:.1f}%"
        tiles = [
            (str(focus.clients), f"Clients on {focus.name}"),
            (f"{focus.util:.0%}", f"Load on {focus.name}"),
            (loss, f"Packet loss on {focus.name}"),
        ]
    colours = ("sky", "yellow", "lavender")
    html(
        '<div class="hero">'
        f'<div class="card bg-{card.tone} status"><div class="icon">{safe_html(card.icon)}</div>'
        f'<div><div class="eye">{safe_html(card.eyebrow)}</div>'
        f'<div class="head">{safe_html(card.headline)}</div></div></div>'
        + "".join(
            f'<div class="card bg-{c} tile"><div class="num">{safe_html(v)}</div>'
            f'<div class="lbl">{safe_html(label)}</div></div>'
            for c, (v, label) in zip(colours, tiles, strict=True)
        )
        + "</div>"
    )


# ---------------------------------------------------------------- the floor plan


def floor_plan(snap: Live) -> None:
    """The campus sheet: title, legend and the floor plan SVG."""
    zones = campus()
    if snap.topology is None:
        html(
            '<div class="sheet-head"><h3>Sheet 1 — Campus floor plan</h3></div>'
            '<p class="on-dark">Waiting for data from the network… The plan appears once the '
            "twin has a state.</p>"
        )
        return
    aps, stations = map_layers(snap.topology)
    hot = [a["name"] for a in aps if a["band"] == "congested"]
    on_hot = f"On congested {hot[0]}" if len(hot) == 1 else "On a congested AP"
    legend = (
        '<div class="legend">'
        f'<span><i class="dot" style="background:{INDIGO}"></i>Client</span>'
        f'<span><i class="dot" style="background:{RED}"></i>{safe_html(on_hot)}</span>'
        f'<span><i class="dot" style="background:{WHITE};border:2px dashed {NAVY};'
        f'box-shadow:0 0 0 1.5px {WHITE}"></i>Proposed move</span>'
        f'<span><b style="color:{RED}">✕</b>No access point</span>'
        '<span><i class="ring"></i>Coverage</span></div>'
    )
    html(
        f'<div class="sheet-head"><h3>Sheet 1 — Campus floor plan</h3>{legend}</div>'
        + floor_plan_svg(aps, stations, zones, map_move(snap.actions))
    )


# ---------------------------------------------------------------- proposal card


APPROVE_WORDS = {"approve": "Approve", "apply": "Apply now"}


def proposal_card(snap: Live, start: datetime | None) -> None:
    """The change that matters most now, with the operator's buttons when it waits."""
    view = proposal_view(snap, now(), watch(), start)
    if view is None:
        html(
            '<div class="eyebrow">Optimiser</div><div class="big-title">No change proposed</div>'
            '<p class="empty">The optimiser proposes one when an access point is congested; '
            "the twin checks it before anything changes.</p>"
        )
        return
    html(
        f'<div class="eyebrow">{safe_html(view.eyebrow)}</div>'
        f'<div class="big-title">{safe_html(view.title)}</div>{twin_boxes(view)}'
    )
    if view.kind == "waiting":
        decide_buttons(view)
    elif view.kind == "watching":
        html(f'<div class="progress"><i style="width:{view.progress:.0%}"></i></div>')
    elif view.note:
        tone = "bg-mint" if view.note.startswith("✓") else "bg-coral"
        html(f'<div class="result {tone}">{safe_html(view.note)}</div>')


def twin_boxes(view: Proposal) -> str:
    """The two "Twin predicts" boxes (latency, loss); coral when the twin rejected it."""
    if view.latency is None or view.loss is None:
        return ""
    css = "twin-box" if view.accepted else "twin-box bad"

    def box(label: str, after: float, before: float, unit: str, fmt: str) -> str:
        was = f"{fmt.format(before)}{unit}"
        trend = f"down from {was}" if after < before else f"up from {was}"
        return (
            f'<div class="{css}"><div class="k">Twin predicts {label}</div>'
            f'<div class="n">{fmt.format(after)}{unit}</div>'
            f'<div class="s">{trend if fmt.format(after) != fmt.format(before) else "no change"}'
            "</div></div>"
        )

    return (
        '<div class="twin-boxes">'
        + box("latency", *view.latency, " ms", "{:.0f}")
        + box("loss", *view.loss, "%", "{:.1f}")
        + "</div>"
    )


def decide_buttons(view: Proposal) -> None:
    """Deny (asked once more: a denied change can never be applied) and Approve / Apply."""
    action_id = view.action_id
    confirming = st.session_state.get("deny") == action_id
    if confirming:
        html('<p class="empty"><b>Deny this change?</b> It can\'t be applied afterwards.</p>')
    left, right = st.columns([1, 1.6])
    with left:
        if confirming:
            st.button(
                "Yes, deny",
                key=f"btn-white-yes-{action_id}",
                on_click=decide,
                args=(action_id, "deny", view.title),
            )
        else:
            st.button(
                "Deny", key=f"btn-white-deny-{action_id}", on_click=ask_deny, args=(action_id,)
            )
    with right:
        if confirming:
            st.button(
                "Keep it", key=f"btn-indigo-keep-{action_id}", on_click=ask_deny, args=(None,)
            )
        else:
            label = APPROVE_WORDS.get(str(view.next_step), "Approve")
            if view.next_step == "approve" and view.title.startswith("Move "):
                label = "Approve move"
            st.button(
                label,
                key=f"btn-indigo-go-{action_id}",
                on_click=decide,
                args=(action_id, str(view.next_step), view.title),
            )


def ask_deny(action_id: str | None) -> None:
    st.session_state["deny"] = action_id


DONE = {"approve": "Approved", "apply": "Applied", "deny": "Denied"}  # the toast after a step


def decide(action_id: str, step: str, what: str) -> None:
    """Send the operator's step to the API (the token stays in this process)."""
    st.session_state["deny"] = None
    try:
        client().operator(action_id, step, by=OPERATOR)
        st.toast(f"{DONE.get(step, step)}: {md_literal(what)}")
    except ApiError as exc:
        st.toast(md_literal(exc))
    read_live.clear()


# ---------------------------------------------------------------- AI copilot


def copilot_card(shown: int | None = SHOWN_CHATS, key: str = "ov") -> None:
    """The copilot: the latest exchanges, then one box for a question or an intent."""
    status = st.session_state.get("llm")
    dot = {"ok": ("ok", "Online"), "off": ("off", "Offline")}.get(str(status), ("idle", "Ready"))
    html(
        '<div class="copilot-head"><h3>AI copilot</h3>'
        f'<span class="online {dot[0]}"><i></i>{dot[1]}</span></div>'
    )
    history: list[dict[str, Any]] = st.session_state.setdefault("chat", [])
    first = 0 if shown is None else max(0, len(history) - shown)
    if not history:
        html(
            '<p class="empty">Ask why something is happening, or say what you want: "Give video '
            'calls in the lecture hall priority." The twin checks every change first.</p>'
        )
    for n in range(first, len(history)):
        exchange(n, history[n], key)
    with (
        st.container(key=f"ask-{key}"),
        st.form(f"ask-form-{key}", clear_on_submit=True, border=False),
    ):
        text_col, send_col = st.columns([5, 1])
        text = text_col.text_input(
            "Ask or tell",
            placeholder="Describe an intent or ask a question",
            label_visibility="collapsed",
        )
        if send_col.form_submit_button("➤", help="Send") and text.strip():
            send(text.strip())


def send(text: str) -> None:
    """A question to the copilot, anything else to the intent engine (panels.route)."""
    kind = route(text)
    path, body = ("/chat", {"question": text}) if kind == "ask" else ("/intents", {"text": text})
    with st.spinner("The copilot is looking at the network…"):
        try:
            reply = client().post(path, body)
            st.session_state["llm"] = "ok"
        except ApiError as exc:
            reply = {"error": str(exc)}
            if "language model" in str(exc):
                st.session_state["llm"] = "off"
    st.session_state.setdefault("chat", []).append(
        {"kind": kind, "text": text, "reply": reply, "applied": False}
    )
    read_live.clear()


def exchange(n: int, item: dict[str, Any], key: str) -> None:
    """One exchange: the operator's words, then the copilot's reply (and its button)."""
    html(f'<div class="bubble you">{safe_html(item["text"])}</div>')
    reply = item["reply"]
    chip = "asked" if item["kind"] == "ask" else "intent"
    if "error" in reply and item["kind"] == "ask":
        html(bubble(chip, f"The copilot could not answer: {safe_html(reply['error'])}"))
        return
    if item["kind"] == "ask":
        tools = sorted({e["tool"] for e in reply.get("evidence", [])})
        used = f'<div class="tools">used {safe_html(", ".join(tools))}</div>' if tools else ""
        tips = "".join(
            '<div class="tools">suggested: '
            f"{safe_html(plain_action(s['action']))} · twin {safe_html(verdict_word(s['verdict']))}"
            "</div>"
            for s in reply.get("suggested_actions", [])
        )
        html(bubble(chip, rich_html(shorten(reply.get("answer", ""))) + used + tips))
        return
    view = intent_view(reply)
    check = ""
    if view.check:
        css, mark = ("ok", "✓") if view.ok else ("no", "✕")
        check = f'<div class="{css}">{mark} {safe_html(view.check)}</div>'
    html(bubble(chip, safe_html(view.text) + check))
    if view.applicable and not item["applied"]:
        st.button(
            "Create and apply policy",
            key=f"btn-yellow-policy-{key}-{n}",
            on_click=apply_policy,
            args=(n, view.applicable),
        )
    elif item["applied"]:
        html('<div class="result bg-mint">✓ Applied · the executor watches it for 30 s</div>')


def bubble(chip: str, body: str) -> str:
    """An AI-written reply: a white bubble marked with what it answers (body escaped)."""
    return f'<div class="bubble"><span class="chip">{chip}</span><br>{body}</div>'


def apply_policy(n: int, action_ids: tuple[str, ...]) -> None:
    """The operator's yes for an intent's twin-accepted set: approve each action that needs
    it, then apply the set (the API applies the whole verified group)."""
    api = client()
    try:
        records = {r["action_id"]: r for r in api.get("/actions")["actions"]}
        for action_id in action_ids:
            r = records.get(action_id)
            if r and r["status"] == "verified" and r["verdict"].get("needs_approval"):
                api.operator(action_id, "approve", by=OPERATOR)
        api.operator(action_ids[0], "apply", by=OPERATOR)
        st.session_state["chat"][n]["applied"] = True
        st.toast("Applied: the policy's changes")
    except ApiError as exc:
        st.toast(md_literal(exc))
    read_live.clear()


# ---------------------------------------------------------------- bottom row


WAITING = '<p class="empty">Waiting for data from the network…</p>'


def ap_card(snap: Live) -> str:
    """The Access points card: zone, channel, clients and a load bar per AP."""
    if snap.topology is None:
        return card("Access points", WAITING, spaced=False)
    zones = campus()
    rows = []
    for r in ap_rows(snap.topology, zones):
        hot = "hot" if r.hot else ""
        rows.append(
            f'<div class="aprow"><div class="chip-ap bg-{r.chip}">{safe_html(r.name)}</div>'
            f'<div><div class="what">{safe_html(r.what)}</div>'
            f'<div class="bar"><i class="{hot}" style="width:{r.width}%"></i></div></div>'
            f'<div class="pct {hot}">{safe_html(r.pct)}</div></div>'
        )
    return card("Access points", "".join(rows), spaced=False)


def event_card(snap: Live, start: datetime | None, limit: int = 5) -> str:
    """The Event timeline card: the newest `limit` events, oldest first."""
    events = event_rows(snap, watch(), start, limit=limit)
    body = "".join(
        f'<div class="ev"><div class="t {e.tone}">{safe_html(e.time)}</div><div>'
        f"<b>{safe_html(e.title)}</b><span>{safe_html(e.detail)}</span></div></div>"
        for e in events
    )
    quiet = '<p class="empty">All quiet: no change proposed and no alert yet.</p>'
    return card("Event timeline", body or quiet, spaced=False)


TWIN_KEYS = (
    '<div class="keys"><span><i style="background:#FF8A73"></i>Before</span>'
    f'<span><i style="background:{LAVENDER};border-style:dashed"></i>Twin predicted</span>'
    f'<span><i style="background:{INDIGO}"></i>Measured live</span></div>'
)


def measured(actions: list[dict[str, Any]] | Any) -> list[dict[str, Any]]:  # Any: a Sequence
    """The changes whose watch measured the network, newest first."""
    done = [r for r in actions if r.get("measured") and r["applied_at"]]
    return sorted(done, key=lambda r: r["applied_at"], reverse=True)


def twin_card(snap: Live, record: dict[str, Any] | None = None) -> str:
    """Before / twin predicted / measured for the newest measured change (or `record`)."""
    if record is None:
        newest = measured(snap.actions)
        record = newest[0] if newest else None
    title = "Twin prediction against measured"
    if record is None:
        body = (
            '<p class="empty">No change has finished its 30 s watch yet. Each one will show the '
            "twin's prediction next to what was measured.</p>"
        )
        return card(title, body, spaced=False)
    v = record["verdict"]
    bars = twin_bars_svg(v["baseline"], v["predicted"], record["measured"])
    outcome = record["status"].replace("_", " ")
    what = (
        f'<p class="empty">{safe_html(plain_action(record["action"]))} · {safe_html(outcome)}</p>'
    )
    return card(title, TWIN_KEYS + bars + what, spaced=False)


# ---------------------------------------------------------------- pages


@st.fragment(run_every=REFRESH)
def overview_top() -> None:
    """Story strip and the hero row (refreshed every few seconds)."""
    snap, clock = live(), demo_clock(run_file(), now())
    if snap is None:
        st.error(f"{md_literal(read_live().get('error', ''))} · this page reconnects by itself.")
        return
    story_strip(snap, clock)
    hero_row(snap, start_of(clock))


@st.fragment(run_every=REFRESH)
def sheet() -> None:
    snap = live()
    if snap is not None:
        floor_plan(snap)


@st.fragment(run_every=REFRESH)
def proposal() -> None:
    snap = live()
    if snap is not None:
        proposal_card(snap, start_of(demo_clock(run_file(), now())))


@st.fragment(run_every=REFRESH)
def bottom_row() -> None:
    snap = live()
    if snap is None:
        return
    start = start_of(demo_clock(run_file(), now()))
    cols = st.columns(3, gap="medium")
    html(ap_card(snap), cols[0])
    html(event_card(snap, start), cols[1])
    html(twin_card(snap), cols[2])


def overview() -> None:
    overview_top()
    left, right = st.columns([1.9, 1], gap="large")
    with left, st.container(key="sheet"):
        sheet()
    with right:
        with st.container(key="card-white-proposal"):
            proposal()
        with st.container(key="card-lavender-copilot"):
            copilot_card()
    bottom_row()


@st.fragment(run_every=REFRESH)
def network_map() -> None:
    snap = live()
    if snap is None:
        return
    with st.container(key="sheet"):
        floor_plan(snap)
    if snap.topology is None:
        return
    aps, stations = map_layers(snap.topology)
    power = {a["name"]: a.get("tx_power_dbm") for a in snap.topology["aps"]}
    rows = "".join(
        table_row(
            f"<b>{safe_html(a['name'])}</b>",
            safe_html(a["channel"]),
            "off" if a["band"] == "down" else f"{a['load']:.0%}",
            safe_html(a["band"]),
            str(a["clients"]),
            "—" if power[a["name"]] is None else f"{power[a['name']]:g} dBm",
            safe_html(", ".join(a["shares_channel_with"]) or "—"),
        )
        for a in aps
    )
    lost = ", ".join(s["name"] for s in stations if s["ap"] == "no AP") or "none"
    head = ("AP", "Channel", "Load", "State", "Clients", "Tx power", "Shares airtime with")
    without = f'<p class="empty">Clients without an access point: {safe_html(lost)}</p>'
    html(card("Access points in detail", table(head, rows) + without))
    charts()


def table_row(*cells: str) -> str:
    """One table row of cells already escaped."""
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def table(head: tuple[str, ...], rows: str, empty: str = "Nothing yet.") -> str:
    """A grid table: a header row, then `rows` (or one row saying it is empty)."""
    header_row = "<tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>"
    body = rows or f'<tr><td colspan="{len(head)}">{empty}</td></tr>'
    return f'<table class="grid">{header_row}{body}</table>'


def card(title: str, body: str, colour: str = "white", spaced: bool = True) -> str:
    """A sorbet card with its title; `spaced` adds the gap above it."""
    gap = ' style="margin-top:22px"' if spaced else ""
    return f'<div class="card bg-{colour}"{gap}><h3>{safe_html(title)}</h3>{body}</div>'


@st.fragment(run_every=CHART_REFRESH)
def charts() -> None:
    """Load per AP and traffic per class over the last 5 minutes (Altair, in the new look)."""
    api = client()
    left, right = st.columns(2, gap="medium")
    try:
        with left, st.container(key="card-white-load"):
            load_chart(api)
        with right, st.container(key="card-white-kpi"):
            kpi_chart(api)
    except ApiError:
        html(
            '<p class="on-dark">Waiting for data from the network… '
            "The charts follow the live run.</p>"
        )


def styled(chart: Any) -> Any:  # Any: altair charts are partly untyped
    return (
        chart.configure(background=WHITE, font="Hanken Grotesk")
        .configure_view(stroke=None)
        .configure_axis(labelColor=MUTED, gridColor="#E3E8F0", domainColor=NAVY, tickColor=NAVY)
        .configure_header(labelColor=NAVY, labelFontWeight="bold", labelFontSize=13)
        .configure_legend(labelColor=NAVY, titleColor=NAVY)
    )


def load_chart(api: ApiClient) -> None:
    html("<h3>Load per AP · last 5 minutes</h3>")
    rows = []
    for a in api.get("/topology")["aps"]:
        points = api.get(f"/metrics?entity={a['name']}&metric=channel_util&window={WINDOW_S}")[
            "points"
        ]
        rows += [{"ap": a["name"], "t": p["ts"], "util": p["value"]} for p in points]
    if not rows:
        html('<p class="empty">No load measured yet.</p>')
        return
    base = alt.Chart(pd.DataFrame(rows))
    line = base.mark_line(strokeWidth=2.5, color=INDIGO).encode(
        x=alt.X("t:T", title=None, axis=alt.Axis(format="%H:%M", labelColor=MUTED)),
        y=alt.Y("util:Q", title=None, scale=alt.Scale(domain=[0, 1.05]), axis=alt.Axis(format="%")),
        tooltip=[
            "ap:N",
            alt.Tooltip("t:T", format="%H:%M:%S"),
            alt.Tooltip("util:Q", format=".0%"),
        ],
    )
    congested = base.mark_rule(strokeDash=[5, 4], color=RED, strokeWidth=2).encode(
        y=alt.datum(CONGESTED)
    )
    chart = (
        alt.layer(line, congested)
        .properties(width=150, height=120)
        .facet(column=alt.Column("ap:N", title=None))
    )
    st.altair_chart(styled(chart))


def kpi_chart(api: ApiClient) -> None:
    html("<h3>Traffic per class · last 5 minutes</h3>")
    points = {
        (c, field): api.get(f"/metrics?entity={c}&metric={field}&window={WINDOW_S}")["points"]
        for c in CLASSES
        for _, field in KPIS
    }
    rows = kpi_series(points)
    if not rows:
        html(
            '<p class="empty">No flow measured yet. The probes report once the traffic starts.</p>'
        )
        return
    line = (
        alt.Chart(pd.DataFrame(rows))
        .mark_line(strokeWidth=2.5)
        .encode(
            x=alt.X("t:T", title=None, axis=alt.Axis(format="%H:%M", labelColor=MUTED)),
            y=alt.Y("value:Q", title=None),
            color=alt.Color(
                "class:N",
                scale=alt.Scale(domain=list(CLASSES), range=list(CLASSES.values())),
                legend=alt.Legend(orient="bottom", title="Traffic class"),
            ),
            tooltip=[
                "class:N",
                "kpi:N",
                alt.Tooltip("t:T", format="%H:%M:%S"),
                alt.Tooltip("value:Q", format=".2f"),
            ],
        )
    )
    chart = (
        line.properties(width=170, height=120)
        .facet(column=alt.Column("kpi:N", title=None, sort=[label for label, _ in KPIS]))
        .resolve_scale(y="independent")
    )
    st.altair_chart(styled(chart))


@st.fragment(run_every=REFRESH)
def digital_twin() -> None:
    """Twin vs measured for the last measured changes, and every twin verdict."""
    snap = live()
    if snap is None:
        return
    done = measured(snap.actions)[:6]
    if not done:
        html(twin_card(snap))
    for i in range(0, len(done), 3):
        cols = st.columns(3, gap="medium")
        for col, record in zip(cols, done[i : i + 3], strict=False):
            html(twin_card(snap, record), col)
    start = start_of(demo_clock(run_file(), now()))
    html(
        card("Every twin check", verdict_table(list(snap.actions), start, "No change checked yet."))
    )


def verdict_row(r: dict[str, Any], start: datetime | None) -> str:
    v = r["verdict"]
    if v.get("accepted"):
        p = v.get("predicted") or {}
        twin = "accepted"
        detail = f"{p.get('latency_ms', 0):.0f} ms · {p.get('loss_pct', 0):.1f}%" if p else "—"
    else:
        twin = "rejected"
        detail = why_not(v).removeprefix("twin: ")
    return (
        f"<tr><td>{safe_html(clock_label(r['action']['created_at'], start))}</td>"
        f"<td>{safe_html(plain_action(r['action']))}</td>"
        f"<td>{safe_html(source_word(r['action'].get('source', '')))}</td>"
        f"<td><b>{twin}</b></td><td>{safe_html(detail)}</td>"
        f"<td>{safe_html(r['status'].replace('_', ' '))}</td></tr>"
    )


def copilot_page() -> None:
    left, right = st.columns([1.2, 1], gap="large")
    with left, st.container(key="card-lavender-copilot-full"):
        copilot_card(shown=None, key="full")
    with right:
        alerts_card()


@st.fragment(run_every=REFRESH)
def alerts_card() -> None:
    """Alert episodes with Explain, and their root-cause reports."""
    snap = live()
    with st.container(key="card-white-alerts"):
        html("<h3>Anomaly alerts</h3>")
        groups = alert_groups(list(snap.alerts)) if snap else []
        if not groups:
            html('<p class="empty">No anomaly alert in the last 10 minutes.</p>')
        start = start_of(demo_clock(run_file(), now()))
        reports: dict[str, Any] = st.session_state.setdefault("rca", {})
        for g in groups[:6]:
            when = safe_html(clock_label(g.first, start))
            html(
                f'<div class="ev"><div class="t coral">{when}</div>'
                f"<div><b>{safe_html(g.entity)} looks unusual</b>"
                f"<span>{g.count} alerts</span></div></div>"
            )
            explain(g, reports)


def explain(group: AlertGroup, reports: dict[str, Any]) -> None:
    key = f"{group.entity}-{group.first}"
    if key in reports:
        html(rca_html(reports[key]))
    elif st.button("Explain", key=f"btn-white-rca-{key}"):
        with st.spinner("Asking the root-cause explainer…"):
            try:
                reports[key] = client().post("/alerts/explain", {"alert": group.latest})
            except ApiError as exc:
                reports[key] = {"error": str(exc)}
        st.rerun(scope="fragment")


def rca_html(report: dict[str, Any]) -> str:
    """A root-cause report in plain words (AI-written: in a bubble, marked as such)."""
    view = rca_view(report)
    if view.error:
        return bubble("AI root cause", f"The explainer could not answer: {safe_html(view.error)}")
    causes = "".join(
        f"<div>likely: <b>{safe_html(cause)}</b> on {safe_html(entity)} ({safe_html(conf)})"
        f" · {safe_html(evidence)}</div>"
        for cause, entity, conf, evidence in view.causes
    )
    tips = "".join(f'<div class="tools">suggested: {safe_html(s)}</div>' for s in view.suggestions)
    source = (
        f'<div class="tools">by {safe_html(view.model)} · evidence from the 5 minutes before '
        "the alert</div>"
    )
    return bubble("AI root cause", rich_html(view.summary) + causes + tips + source)


@st.fragment(run_every=REFRESH)
def policies() -> None:
    """The intents of this session and every change the AI proposed."""
    intents = [c for c in st.session_state.get("chat", []) if c["kind"] == "intent"]
    items = "".join(
        f'<div class="bubble you">{safe_html(c["text"])}</div>'
        + bubble(
            "intent",
            safe_html(intent_view(c["reply"]).text)
            + ('<div class="ok">✓ applied</div>' if c["applied"] else ""),
        )
        for c in reversed(intents)
    )
    none = '<p class="empty">No intent sent yet. Use the copilot box on the Overview page.</p>'
    html(card("Intents this session", items or none, "lavender", spaced=False))
    snap = live()
    if snap is None:
        return
    start = start_of(demo_clock(run_file(), now()))
    ai = [r for r in snap.actions if r["action"].get("source", "").startswith("llm")]
    html(card("Changes the AI proposed", verdict_table(ai, start, "None yet.")))


VERDICT_HEAD = ("Time", "Change", "From", "Twin", "Predicted latency · loss", "Status")


def verdict_table(records: list[dict[str, Any]], start: datetime | None, empty: str) -> str:
    """Every twin check of `records`, newest first."""
    newest = sorted(records, key=lambda r: r["action"]["created_at"], reverse=True)
    return table(VERDICT_HEAD, "".join(verdict_row(r, start) for r in newest), empty)


@st.fragment(run_every=REFRESH)
def history() -> None:
    """The full action ledger and the recent alerts, as tables."""
    snap = live()
    if snap is None:
        return
    start = start_of(demo_clock(run_file(), now()))
    html(event_card(snap, start, limit=40))
    ledger = "".join(
        table_row(
            safe_html(clock_label(r["action"]["created_at"], start)),
            f"<code>{safe_html(r['action_id'])}</code>",
            safe_html(plain_action(r["action"])),
            safe_html(source_word(r["action"].get("source", ""))),
            safe_html(r["status"].replace("_", " ")),
            safe_html(r.get("note") or ""),
        )
        for r in sorted(snap.actions, key=lambda r: r["action"]["created_at"], reverse=True)
    )
    head = ("Time", "Id", "Change", "From", "Status", "Note")
    empty = "Empty: no change recorded in this run."
    html(card("Action ledger", table(head, ledger, empty)))


# ---------------------------------------------------------------- the page


def main() -> None:
    """The page: style, header, the six pages as pills, then the selected page."""
    st.set_page_config(page_title="Campus Wi-Fi Twin", page_icon="📶", layout="wide")
    html(CSS)
    header()
    with st.container(key="nav"):
        page = (
            st.pills("Page", TABS, default=TABS[0], key="page", label_visibility="collapsed")
            or TABS[0]
        )
    {
        "Overview": overview,
        "Network map": network_map,
        "Digital twin": digital_twin,
        "AI copilot": copilot_page,
        "Policies": policies,
        "History and logs": history,
    }[page]()


if __name__ == "__main__":  # `streamlit run` executes this file as __main__
    main()
