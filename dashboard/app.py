"""P6.1 operator dashboard (Streamlit): what is happening on the network, what the system is doing
about it and what the twin predicted, and the operator's yes or no. Redesigned for the live demo
(deviation #19, docs/superpowers/specs/2026-10-16-dashboard-redesign-design.md).

    make dashboard     # streamlit on http://127.0.0.1:8501 (needs `make api`)

Talks to the P3.6 API over HTTP only (dashboard/client.py). The operator token stays in this
server process (OPERATOR_TOKEN in .env) and is never sent to the browser. Every string from the
API is escaped before it goes into HTML: reasons, answers and reports can be written by the LLM
(rule L-6).
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
import yaml

from dashboard.client import ApiClient, ApiError
from dashboard.views import (
    CONGESTED,
    COVERAGE_M,
    KPIS,
    Item,
    kpi_series,
    latest_steer,
    map_layers,
    plain_action,
    rca_view,
    rich_html,
    safe_html,
    status,
    tiles,
    timeline,
    twin_vs_live,
    verdict_word,
)

ROOT = Path(__file__).resolve().parents[1]
API_URL = os.getenv("DASHBOARD_API_URL", "http://127.0.0.1:8000")
OPERATOR = os.getenv("OPERATOR_NAME", "operator")
REFRESH = "5s"  # the live panels
CHART_REFRESH = "15s"  # the chart card: up to 9 series queries a refresh
# style F "soft modern" (design §4.7); text on white passes WCAG AA
INK, MUTED, LINE, ACCENT = "#1C2433", "#5B6475", "#E3E8F0", "#2A78D6"
# AP load, as a status scale (dataviz palette checks on #F7F9FC: CVD and normal-vision pass;
# calm and busy are under 3:1 contrast, so every disc carries its text label)
LOAD = {"calm": "#2A78D6", "busy": "#D18A00", "congested": "#D03B3B", "down": "#FFFFFF"}
HALO = "#F6D6D6"  # the glow behind a congested AP
CRITICAL = "#D03B3B"  # also: stations without an AP
CHANNELS = {"ch 1": "#2F5FD0", "ch 6": "#C2701A", "ch 11": "#1E9E6A"}  # coverage rings only
DASHES = {"ch 1": [1, 0], "ch 6": [8, 4], "ch 11": [2, 4]}  # second cue besides colour
CLASSES = {"video": "#7B4FC4", "web": "#C23B7A", "bulk": "#4F6B12"}  # traffic classes
SOURCES = {"before": "#C9D2DE", "twin predicted": ACCENT, "measured": INK}
PX_PER_M = 7  # map scale: the floor plan (config/campus_v1.yaml zones) at 7 px per metre
CHARTS = ("Load per AP", "Traffic KPIs", "Twin vs measured")
WINDOW_S = 300  # the charts' window, as their titles say ("last 5 minutes")
ALERTS_S = 600  # alerts this recent make the timeline's episodes
LATEST = 3  # changes in the twin-vs-measured chart; copilot exchanges in the sidebar
ARROW_HEAD = 0.75  # where the steer arrow's head sits between the APs: clear of the target disc
RCA_WINDOW = "5 minutes"  # genai/rca/evidence.py WINDOW_S: the evidence before the alert
STEP = {  # timeline kind → the words before its time
    "waiting": "waiting for you",
    "applied": "applied",
    "checked": "twin checked",
    "outcome": "after the watch",
    "detected": "detected",
}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600;700&display=swap');
html {{ font-size: 17px; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 2rem; }}
html, body, [class*="css"], .stMarkdown {{ font-family: 'IBM Plex Sans', sans-serif;
  color: {INK}; }}
.stApp {{ background: linear-gradient(160deg, #EEF3FB 0%, #F8F6F2 100%); }}
[data-testid="stSidebar"] > div:first-child {{ background: #F7F9FC; }}
/* no fading: Streamlit dims what is being re-run, every few seconds here (design §4.7) */
[data-stale="true"], .stale-element {{ opacity: 1 !important; filter: none !important;
  transition: none !important; }}
/* cards: the containers keyed card-… */
[class*="st-key-card"] {{ background: #FFFFFF; border-radius: 14px; padding: 14px 16px;
  box-shadow: 0 2px 8px rgba(20,33,61,.08); }}
.eyebrow {{ text-transform: uppercase; font-size: .72rem; font-weight: 600; color: {MUTED};
  letter-spacing: .06em; margin-bottom: .3rem; }}
.title {{ font-size: 1.9rem; font-weight: 700; line-height: 1.1; }}
.live {{ background: #E1F5EA; color: #1F7A4D; border-radius: 12px; padding: 3px 12px;
  font-size: .8rem; float: right; margin-top: .4rem; }}
.banner {{ background: #FFFFFF; border-radius: 14px; padding: 14px 18px; font-size: 1.15rem;
  box-shadow: 0 2px 8px rgba(20,33,61,.08); display: flex; gap: 14px; align-items: center;
  margin: .6rem 0; }}
.banner .dot {{ width: 13px; height: 13px; border-radius: 50%; flex: none; }}
.banner.critical .dot {{ background: {CRITICAL}; box-shadow: 0 0 0 6px {HALO}; }}
.banner.attention .dot {{ background: {LOAD["busy"]}; box-shadow: 0 0 0 6px #F8E7C6; }}
.banner.calm .dot {{ background: #1F9D63; box-shadow: 0 0 0 6px #DDF3E7; }}
.banner.waiting .dot {{ background: #8A93A6; box-shadow: 0 0 0 6px #ECEFF4; }}
.banner .doing {{ color: {MUTED}; }}
.tiles {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: .8rem; }}
.tile {{ background: #FFFFFF; border-radius: 12px; padding: 10px 14px;
  box-shadow: 0 2px 6px rgba(20,33,61,.06); }}
.tile .v {{ font-size: 2rem; font-weight: 700; line-height: 1.1; }}
.tile .l {{ font-size: .85rem; color: {MUTED}; }}
.tone-critical {{ color: {CRITICAL}; }} .tone-action {{ color: {ACCENT}; }}
.tone-good {{ color: #1F7A4D; }} .tone-warn {{ color: #B45309; }}
.item {{ border-left: 2px solid {LINE}; margin-left: 6px; padding: 0 0 .7rem 16px;
  position: relative; font-size: .92rem; }}
.item::before {{ content: ""; position: absolute; left: -7px; top: .35rem; width: 12px;
  height: 12px; border-radius: 50%; background: #9AA4B5; }}
.item.critical::before {{ background: {CRITICAL}; }}
.item.action::before {{ background: {ACCENT}; }}
.item.good::before {{ background: #1F9D63; }} .item.warn::before {{ background: #D97706; }}
.item.waiting {{ background: #F3F8FF; border: 1px solid #CFE0F7; border-radius: 10px;
  padding: 8px 10px 8px 18px; margin-bottom: .5rem; }}
.item .meta {{ color: {MUTED}; font-size: .8rem; }}
.item .what {{ font-weight: 600; }}
.item .detail {{ color: {MUTED}; font-size: .85rem; }}
.pill {{ display: inline-block; border-radius: 9px; padding: 0 8px; font-size: .78rem;
  font-weight: 600; margin-left: 4px; }}
.pill.good {{ background: #E1F5EA; color: #1F7A4D; }}
.pill.warn {{ background: #FDEBD3; color: #9A4A06; }}
.pill.critical {{ background: #FBE3E3; color: #A62B2B; }}
.pill.action {{ background: #E3EDFB; color: #1F5FAF; }}
.pill.calm {{ background: #EEF1F6; color: {MUTED}; }}
.rca {{ background: #FBF7F5; border-radius: 8px; padding: 8px 10px; margin-top: .3rem;
  font-size: .85rem; line-height: 1.45; }}
.legend {{ color: {MUTED}; font-size: .8rem; display: flex; gap: 14px; flex-wrap: wrap; }}
.legend b {{ font-size: 1rem; }}
.bubble {{ border-radius: 12px; padding: 8px 10px; margin: 6px 0; font-size: .88rem;
  line-height: 1.45; background: #FFFFFF; box-shadow: 0 1px 4px rgba(20,33,61,.06); }}
.bubble.you {{ background: #E8F0FB; }}
.bubble .tools {{ color: {MUTED}; font-size: .78rem; }}
</style>
"""


@st.cache_resource
def client() -> ApiClient:
    return ApiClient(API_URL, os.getenv("OPERATOR_TOKEN") or None)


def config(name: str) -> dict[str, Any]:
    """A file of config/, parsed (static settings, read once through the cached callers)."""
    raw: dict[str, Any] = yaml.safe_load((ROOT / "config" / name).read_text())
    return raw


@st.cache_data
def campus_zones() -> list[dict[str, Any]]:
    """Zone rectangles from the campus layout file (static layout, not live state)."""
    raw = config("campus_v1.yaml")
    return [
        {
            "zone": name.replace("_", " "),
            "x": z["x"][0],
            "x2": z["x"][1],
            "y": z["y"][0],
            "y2": z["y"][1],
        }
        for name, z in raw["zones"].items()
    ]


def extent(zones: list[dict[str, Any]], axis: str) -> tuple[float, float]:
    """The floor plan's extent along `axis` ("x" or "y"), in metres."""
    return min(z[axis] for z in zones), max(z[f"{axis}2"] for z in zones)


@st.cache_data
def watch() -> timedelta:
    """How long the executor watches a change after applying it (config/executor.yaml)."""
    raw = config("executor.yaml")
    return timedelta(seconds=raw["watch_s"])


def local_time(iso: str) -> str:
    """HH:MM:SS on this machine's clock, like the chart axes (the API speaks UTC)."""
    return datetime.fromisoformat(iso).astimezone().strftime("%H:%M:%S")


def eyebrow(text: str, where: Any = st) -> None:  # Any: st, st.sidebar or a container
    where.markdown(f'<div class="eyebrow">{safe_html(text)}</div>', unsafe_allow_html=True)


def white(chart: Any) -> Any:  # Any: altair charts are partly untyped
    """A faceted chart on the card's white, not the page's grey."""
    return chart.configure(background="#FFFFFF").configure_view(stroke=None)


def frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Chart data (a DataFrame: typed, unlike altair's inline Data)."""
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- the campus map


def campus_map(topology: dict[str, Any], actions: list[dict[str, Any]]) -> Any:  # Any: altair
    """The floor plan: AP discs coloured by load with their labels, faint coverage rings in
    the channel's colour, the stations, and an arrow for the steer being watched."""
    aps, stations = map_layers(topology)
    plan = campus_zones()
    (x0, x1), (y0, y1) = extent(plan, "x"), extent(plan, "y")  # the map is the floor plan
    x = alt.X("x:Q", scale=alt.Scale(domain=[x0, x1]), axis=None)
    y = alt.Y("y:Q", scale=alt.Scale(domain=[y0, y1]), axis=None)
    # every layer shares the axis-less x and y: one layer with default axes makes Vega fail to
    # merge the axes ("Cannot read properties of undefined (reading 'forEach')", found in P6.2)
    zones = alt.Chart(frame(plan))
    zone_box = zones.mark_rect(fill="#F7F9FC", stroke=LINE, strokeWidth=1).encode(
        x=x, x2="x2:Q", y=y, y2="y2:Q"
    )
    top = alt.Y("y2:Q", scale=alt.Scale(domain=[y0, y1]), axis=None)
    zone_name = zones.mark_text(
        align="left", baseline="top", dx=8, dy=8, color="#8A93A6", fontSize=12
    ).encode(x=x, y=top, text="zone:N")
    up = alt.Chart(frame([a for a in aps if a["band"] != "down"]))
    rings = up.mark_point(
        shape="circle",
        filled=False,
        size=math.pi * (COVERAGE_M * PX_PER_M) ** 2,
        strokeWidth=1.5,
        opacity=0.35,
        clip=True,
    ).encode(
        x=x,
        y=y,
        color=alt.Color(
            "channel:N",
            scale=alt.Scale(domain=list(CHANNELS), range=list(CHANNELS.values())),
            legend=None,
        ),
        strokeDash=alt.StrokeDash(
            "channel:N",
            scale=alt.Scale(domain=list(DASHES), range=list(DASHES.values())),
            legend=None,
        ),
    )
    station_layer = (
        alt.Chart(frame(stations))
        .mark_point(filled=True, size=36)
        .encode(
            x=x,
            y=y,
            shape=alt.condition(alt.datum.ap == "no AP", alt.value("cross"), alt.value("circle")),
            color=alt.condition(alt.datum.ap == "no AP", alt.value(CRITICAL), alt.value("#B8C2D3")),
            tooltip=[alt.Tooltip("name:N", title="client"), alt.Tooltip("ap:N", title="on")],
        )
    )
    ap_chart = alt.Chart(frame(aps))
    halo = (
        ap_chart.transform_filter(alt.datum.band == "congested")
        .mark_point(shape="circle", filled=True, size=2600, color=HALO, opacity=1)
        .encode(x=x, y=y)
    )
    discs = ap_chart.mark_point(shape="circle", filled=True, size=900, strokeWidth=3).encode(
        x=x,
        y=y,
        fill=alt.Fill(
            "band:N",
            scale=alt.Scale(domain=list(LOAD), range=list(LOAD.values())),
            legend=None,
        ),
        stroke=alt.condition(alt.datum.band == "down", alt.value("#8A93A6"), alt.value("#FFFFFF")),
        tooltip=[
            alt.Tooltip("label:N", title="AP"),
            alt.Tooltip("channel:N"),
            alt.Tooltip("shares_channel_with:N", title="shares airtime with"),
        ],
    )
    # the label twice: a thick white outline first, so stations and rings never hide it
    label_halo = ap_chart.mark_text(
        dy=30, fontSize=13, fontWeight=600, stroke="#FFFFFF", strokeWidth=5, strokeJoin="round"
    ).encode(x=x, y=y, text="label:N")
    labels = ap_chart.mark_text(dy=30, fontSize=13, fontWeight=600, color=INK).encode(
        x=x, y=y, text="label:N"
    )
    channel = ap_chart.mark_text(dy=46, fontSize=11, color="#8A93A6").encode(
        x=x, y=y, text="channel:N"
    )
    layers = [zone_box, zone_name, rings, station_layer, *steer_arrow(actions, aps, x, y)]
    layers += [halo, discs, label_halo, labels, channel]
    return (
        alt.layer(*layers)
        .properties(width=(x1 - x0) * PX_PER_M, height=(y1 - y0) * PX_PER_M, background="#FFFFFF")
        .configure_view(strokeWidth=0)
    )


def steer_arrow(
    actions: list[dict[str, Any]], aps: list[dict[str, Any]], x: Any, y: Any
) -> list[Any]:
    """The dashed arrow of the steer being watched, its head before the target disc."""
    arrow = latest_steer(actions, aps)
    if arrow is None:
        return []
    dx, dy = arrow["x2"] - arrow["x"], arrow["y2"] - arrow["y"]
    head = {  # 75% of the way: clear of the target's disc and label
        "x": arrow["x"] + ARROW_HEAD * dx,
        "y": arrow["y"] + ARROW_HEAD * dy,
        "label": arrow["label"],
    }
    line = (
        alt.Chart(frame([arrow]))
        .mark_rule(color=ACCENT, strokeWidth=2.5, strokeDash=[6, 4])
        .encode(x=x, y=y, x2="x2:Q", y2="y2:Q")
    )
    # triangle-up points to +y; Vega turns it clockwise by `angle` degrees
    tip = (
        alt.Chart(frame([head]))
        .mark_point(shape="triangle-up", filled=True, size=220, color=ACCENT)
        .encode(x=x, y=y, angle=alt.value(math.degrees(math.atan2(dx, dy))))
    )
    words = (
        alt.Chart(frame([head]))
        .mark_text(dx=14, align="left", fontSize=12, fontWeight=600, color=ACCENT)
        .encode(x=x, y=y, text="label:N")
    )
    return [line, tip, words]


MAP_LEGEND = (
    '<div class="legend">'
    + "".join(
        f'<span><b style="color:{LOAD[b]}">●</b> {b}</span>' for b in ("calm", "busy", "congested")
    )
    + '<span><b style="color:#8A93A6">○</b> down</span>'
    + f'<span><b style="color:{CRITICAL}">✕</b> client without an AP</span>'
    + f'<span><b style="color:{ACCENT}">⤏</b> clients being moved</span>'
    + f"<span>faint rings: {COVERAGE_M:.0f} m coverage, coloured by channel</span>"
    + "</div>"
)

# ---------------------------------------------------------------- the live panels


@st.fragment(run_every=REFRESH)
def live() -> None:
    """Everything that follows the network; re-drawn every few seconds."""
    api = client()
    try:
        actions = api.get("/actions")["actions"]
    except ApiError as exc:
        st.error(f"The API is not reachable at {API_URL}: {exc}. Start it with `make api`.")
        return
    try:  # 503 before the run's first telemetry: the timeline still shows
        topology: dict[str, Any] | None = api.get("/topology")
    except ApiError:
        topology = None
    try:
        alerts = api.get(f"/alerts?since={ALERTS_S}")["alerts"]
    except ApiError:
        alerts = []
    header(topology)
    banner(topology, actions)
    left, right = st.columns([1, 1.25], gap="medium")
    with left, st.container(key="card-timeline"):
        story(actions, alerts)
    with right, st.container(key="card-map"):
        if topology is None:
            eyebrow("Campus · twin view")
            st.markdown(
                "Waiting for data from the network… The map appears once the twin has a state."
            )
        else:
            eyebrow(f"Campus · twin view at {local_time(topology['ts'])}")
            st.altair_chart(campus_map(topology, actions), width="content")
            st.markdown(MAP_LEGEND, unsafe_allow_html=True)


def header(topology: dict[str, Any] | None) -> None:
    """The title and the live pill with the twin state's time."""
    when = f"twin state {local_time(topology['ts'])}" if topology else "waiting for data"
    st.markdown(
        f'<span class="live">● live · {safe_html(when)}</span>'
        '<div class="eyebrow">GenAI-driven digital twin · SDN Wi-Fi</div>'
        '<div class="title">Campus Wi-Fi twin</div>',
        unsafe_allow_html=True,
    )


def banner(topology: dict[str, Any] | None, actions: list[dict[str, Any]]) -> None:
    """The status banner and its four big numbers."""
    s = status(topology, campus_zones(), actions)
    doing = f' <span class="doing">{safe_html(s.doing)}</span>' if s.doing else ""
    tiles_html = "".join(
        f'<div class="tile"><div class="v tone-{t.tone}">{safe_html(t.value)}</div>'
        f'<div class="l">{safe_html(t.label)}</div></div>'
        for t in tiles(topology, actions)
    )
    st.markdown(
        f'<div class="banner {s.level}"><div class="dot"></div><div><b>{safe_html(s.headline)}</b>'
        f'{doing}</div></div><div class="tiles">{tiles_html}</div>',
        unsafe_allow_html=True,
    )


def story(actions: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> None:
    """The "What is happening" timeline: waiting changes with their buttons on top, then the
    twin's checks, outcomes and alert episodes, newest first."""
    eyebrow("What is happening · newest first")
    items = timeline(actions, alerts, watch=watch())
    if not items:
        st.markdown("All quiet: no change proposed and no alert yet.")
    for item in items:
        st.markdown(item_html(item), unsafe_allow_html=True)
        if item.kind == "waiting" and item.action_id:
            decide_buttons(item)
        if item.kind == "detected" and item.group:
            explain_button(item)


def item_html(item: Item) -> str:
    """One timeline item as HTML (every API string escaped)."""
    detail = f'<div class="detail">{safe_html(item.detail)}</div>' if item.detail else ""
    css = "waiting action" if item.kind == "waiting" else item.tone
    return (
        f'<div class="item {css}"><div class="meta">{local_time(item.at)} · {STEP[item.kind]}</div>'
        f'<span class="what">{safe_html(item.title)}</span>'
        f'<span class="pill {item.tone}">{safe_html(item.badge)}</span>{detail}</div>'
    )


def decide_buttons(item: Item) -> None:
    """Approve or Apply now, and Deny, under a waiting change."""
    action_id = str(item.action_id)
    go, no, _ = st.columns([1, 1, 2])
    label = "Approve" if item.next_step == "approve" else "Apply now"
    go.button(
        label,
        key=f"go-{action_id}",
        type="primary",
        on_click=decide,
        args=(action_id, str(item.next_step)),
    )
    no.button("Deny", key=f"no-{action_id}", on_click=decide, args=(action_id, "deny"))


def decide(action_id: str, step: str) -> None:
    """Send the operator's step to the API (the token stays in this process)."""
    try:
        client().operator(action_id, step, by=OPERATOR)
        st.toast(f"{'Applied' if step == 'apply' else step.capitalize() + 'd'}: {action_id}")
    except ApiError as exc:
        st.toast(str(exc))


def explain_button(item: Item) -> None:
    """Explain under an alert episode, or its root cause once asked for."""
    group = item.group
    assert group is not None  # noqa: S101 - only called for detected items, which carry one
    key = f"{group.entity}-{group.first}"
    reports: dict[str, dict[str, Any]] = st.session_state.setdefault("rca", {})
    if key in reports:
        st.markdown(rca_html(reports[key]), unsafe_allow_html=True)
    elif st.button("Explain", key=f"rca-{key}"):
        with st.spinner("Asking the root-cause explainer…"):
            try:
                reports[key] = client().post("/alerts/explain", {"alert": group.latest})
            except ApiError as exc:
                reports[key] = {"error": str(exc)}
        st.rerun(scope="fragment")


def rca_html(report: dict[str, Any]) -> str:
    """A root-cause report as HTML, in plain words."""
    view = rca_view(report)
    if view.error:
        return f'<div class="rca">The explainer could not answer: {safe_html(view.error)}</div>'
    causes = "".join(
        f"<div>likely: <b>{safe_html(cause)}</b> on {safe_html(entity)} ({safe_html(conf)})"
        f" · {safe_html(evidence)}</div>"
        for cause, entity, conf, evidence in view.causes
    )
    tips = "".join(f"<div>suggested: {safe_html(s)}</div>" for s in view.suggestions)
    return (
        f'<div class="rca"><b>Root cause:</b> {rich_html(view.summary)}{causes}{tips}'
        f'<div style="color:{MUTED}">model {safe_html(view.model)}'
        f" · evidence from the {RCA_WINDOW} before the alert"
        "</div></div>"
    )


# ---------------------------------------------------------------- the chart card


@st.fragment(run_every=CHART_REFRESH)
def charts() -> None:
    """One chart at a time, picked with a control that keeps its choice across refreshes."""
    with st.container(key="card-charts"):
        choice = st.segmented_control(
            "Chart", CHARTS, default=CHARTS[0], key="chart", label_visibility="collapsed"
        )
        api = client()
        try:
            if choice == "Traffic KPIs":
                kpi_card(api)
            elif choice == "Twin vs measured":
                twin_card(api.get("/actions")["actions"])
            else:
                load_card(api)
        except ApiError:
            st.markdown("Waiting for data from the network… The charts follow the live run.")


def load_card(api: ApiClient) -> None:
    """Load per AP over the chart window, one panel per AP."""
    eyebrow("Load per AP · last 5 minutes · congested above the red line")
    rows = []
    for a in api.get("/topology")["aps"]:
        points = api.get(f"/metrics?entity={a['name']}&metric=channel_util&window={WINDOW_S}")[
            "points"
        ]
        rows += [{"ap": a["name"], "t": p["ts"], "util": p["value"]} for p in points]
    if not rows:
        st.markdown("No load measured yet.")
        return
    base = alt.Chart(frame(rows))
    line = base.mark_line(strokeWidth=2, color=ACCENT).encode(
        x=alt.X("t:T", title=None, axis=alt.Axis(format="%H:%M:%S", labelColor=MUTED)),
        y=alt.Y("util:Q", title=None, scale=alt.Scale(domain=[0, 1.05]), axis=alt.Axis(format="%")),
        tooltip=[
            "ap:N",
            alt.Tooltip("t:T", format="%H:%M:%S"),
            alt.Tooltip("util:Q", format=".0%"),
        ],
    )
    congested = base.mark_rule(strokeDash=[4, 3], color=CRITICAL).encode(y=alt.datum(CONGESTED))
    chart = (
        alt.layer(line, congested)
        .properties(width=210, height=130)
        .facet(column=alt.Column("ap:N", title=None))
    )
    st.altair_chart(white(chart))


def kpi_card(api: ApiClient) -> None:
    """Throughput, latency and loss per traffic class over the chart window."""
    eyebrow("Traffic per class · last 5 minutes · mean over 10 s")
    points = {
        (c, field): api.get(f"/metrics?entity={c}&metric={field}&window={WINDOW_S}")["points"]
        for c in CLASSES
        for _, field in KPIS
    }
    rows = kpi_series(points)
    if not rows:
        st.markdown("No flow measured yet. The probes report once the scenario's traffic starts.")
        return
    line = (
        alt.Chart(frame(rows))
        .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=24))
        .encode(
            x=alt.X("t:T", title=None, axis=alt.Axis(format="%H:%M:%S", labelColor=MUTED)),
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
        line.properties(width=260, height=140)
        .facet(column=alt.Column("kpi:N", title=None, sort=[label for label, _ in KPIS]))
        .resolve_scale(y="independent")
    )
    st.altair_chart(white(chart))


def twin_card(actions: list[dict[str, Any]]) -> None:
    """Before, twin predicted and measured for the latest finished changes."""
    eyebrow("Twin prediction vs what happened · the latest 3 changes")
    finished = [r for r in actions if r.get("measured")]
    latest = sorted(finished, key=lambda r: r["applied_at"] or "")[-LATEST:]
    names = {
        r["action_id"]: f"{local_time(r['applied_at'])} · {plain_action(r['action'])}"
        for r in latest
    }
    rows = [row | {"what": names[row["action"]]} for row in twin_vs_live(latest)]
    if not rows:
        st.markdown(
            "No change has finished its watch yet. Each one will show the twin's prediction"
            " next to what was measured."
        )
        return
    sources = list(SOURCES)
    bars = (
        alt.Chart(frame(rows))
        .mark_bar(cornerRadiusEnd=4, height=14)
        .encode(
            y=alt.Y("source:N", sort=sources, title=None, axis=alt.Axis(labels=False, ticks=False)),
            x=alt.X("value:Q", title=None),
            color=alt.Color(
                "source:N",
                scale=alt.Scale(domain=sources, range=list(SOURCES.values())),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=[
                "what:N",
                "kpi:N",
                "source:N",
                alt.Tooltip("value:Q", format=".2f"),
                "outcome:N",
            ],
        )
    )
    chart = (
        bars.properties(width=240, height=60)
        .facet(
            row=alt.Row(
                "what:N",
                title=None,
                header=alt.Header(
                    labelAngle=0, labelAlign="left", labelOrient="top", labelFontSize=13
                ),
            ),
            column=alt.Column("kpi:N", title=None),
        )
        .resolve_scale(x="independent")
    )
    st.altair_chart(white(chart))


# ---------------------------------------------------------------- the sidebar


def sidebar() -> None:
    """The copilot chat and the intent box."""
    api = client()
    eyebrow("💬 Ask the network", st.sidebar)
    history = st.session_state.setdefault("chat", [])
    for question, reply in history[-LATEST:]:
        st.sidebar.markdown(chat_html(question, reply), unsafe_allow_html=True)
    question = st.sidebar.chat_input("Why is video slow in the lecture hall?")
    if question:
        with st.sidebar, st.spinner("The copilot is looking at the network…"):
            try:
                reply = api.post("/chat", {"question": question})
            except ApiError as exc:
                reply = {"error": str(exc)}
        history.append((question, reply))
        st.rerun()
    eyebrow("🎯 Tell the network what you want", st.sidebar)
    with st.sidebar.form("intent", clear_on_submit=True):
        text = st.text_input(
            "Intent",
            placeholder="Give video calls in the lecture hall priority.",
            label_visibility="collapsed",
        )
        if st.form_submit_button("Send intent", type="primary") and text:
            send_intent(api, text)


def chat_html(question: str, reply: dict[str, Any]) -> str:
    """One copilot exchange as two bubbles: the question, and the answer with its tools."""
    answer = reply.get("answer") or f"The copilot could not answer: {reply.get('error', '')}"
    tools = sorted({e["tool"] for e in reply.get("evidence", [])})
    used = f'<div class="tools">used {safe_html(", ".join(tools))}</div>' if tools else ""
    tips = "".join(
        f'<div class="tools">suggested: {safe_html(plain_action(s["action"]))}'
        f" · twin {safe_html(verdict_word(s['verdict']))}</div>"
        for s in reply.get("suggested_actions", [])
    )
    return (
        f'<div class="bubble you"><b>You:</b> {safe_html(question)}</div>'
        f'<div class="bubble">{rich_html(answer)}{used}{tips}</div>'
    )


def send_intent(api: ApiClient, text: str) -> None:
    """Send an intent; show its actions in plain words with the twin's verdict."""
    try:
        result = api.post("/intents", {"text": text})
    except ApiError as exc:
        st.error(str(exc))
        return
    if result["error"]:
        st.error(result["error"])
    for a in result["actions"]:
        verdict = verdict_word(result["verdicts"][a["action_id"]])
        tone = "good" if verdict == "accepted" else "warn"
        st.markdown(
            f'<div class="bubble">{safe_html(plain_action(a))}'
            f'<span class="pill {tone}">twin {safe_html(verdict)}</span></div>',
            unsafe_allow_html=True,
        )


def main() -> None:
    st.set_page_config(page_title="Campus Wi-Fi twin", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    sidebar()
    live()
    charts()


if __name__ == "__main__":  # `streamlit run` executes this file as __main__
    main()
