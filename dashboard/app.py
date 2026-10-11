"""P6.1 operator dashboard (Streamlit): what the network is doing, what the system is doing about
it and why, and the operator's yes or no.

    make dashboard     # streamlit on http://127.0.0.1:8501 (needs `make api`)

Talks to the P3.6 API over HTTP only (dashboard/client.py). The operator token stays in this
server process (OPERATOR_TOKEN in .env) and is never sent to the browser.
"""

from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
import yaml

from dashboard.client import ApiClient, ApiError
from dashboard.views import (
    BANDS,
    CONGESTED,
    COVERAGE_M,
    KPIS,
    decision_queue,
    describe,
    kpi_series,
    map_layers,
    twin_vs_live,
    verdict_word,
)

ROOT = Path(__file__).resolve().parents[1]
API_URL = os.getenv("DASHBOARD_API_URL", "http://127.0.0.1:8000")
OPERATOR = os.getenv("OPERATOR_NAME", "operator")
REFRESH = "5s"
# colours (validated with the dataviz palette checks: CVD and contrast pass on #EEF2F5)
PAPER, INK, MUTED, GRID = "#EEF2F5", "#14212B", "#5B6B78", "#CBD5DD"
CHANNELS = {"ch 1": "#2F5FD0", "ch 6": "#C2701A", "ch 11": "#1E9E6A"}
CHANNEL_SCALE = alt.Scale(domain=list(CHANNELS), range=list(CHANNELS.values()))
DASHES = {"ch 1": [1, 0], "ch 6": [8, 4], "ch 11": [2, 4]}  # second cue besides colour
LOAD = {"calm": "#D3DBE2", "busy": "#8797A6", "congested": "#2A3946", "down": "#FFFFFF"}
CRITICAL = "#B3261E"  # reserved: stations without an AP, alerts
# traffic classes: hues apart from the channel colours (dataviz checks pass on #EEF2F5)
CLASSES = {"video": "#7B4FC4", "web": "#C23B7A", "bulk": "#4F6B12"}
KPI_REFRESH = "15s"  # 9 series queries a refresh: slower than the map
MAP_W, MAP_H, CAMPUS_W, CAMPUS_H = 560, 490, 80, 70  # px and metres (7 px per metre)

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;600&display=swap');
html, body, [class*="css"] {{ font-family: 'IBM Plex Sans', sans-serif; color: {INK}; }}
h1, h2, h3, .eyebrow {{ font-family: 'IBM Plex Sans Condensed', sans-serif; }}
h1 {{ font-size: 1.9rem; margin-bottom: 0; }}
.eyebrow {{ text-transform: uppercase; font-size: .78rem; color: {MUTED}; letter-spacing: .08em; }}
.mono, code, [data-testid="stMetricValue"] {{ font-family: 'IBM Plex Mono', monospace; }}
.card {{ border: 1px solid {GRID}; border-left: 4px solid {INK}; padding: .6rem .8rem;
        margin: .4rem 0; background: #FFFFFF; border-radius: 4px; }}
.card.high {{ border-left-color: {CRITICAL}; }}
.card .what {{ font-family: 'IBM Plex Mono', monospace; font-weight: 600; }}
.card .twin {{ font-family: 'IBM Plex Mono', monospace; font-size: .85rem; color: {MUTED}; }}
.alert {{ border-left: 4px solid {CRITICAL}; padding: .4rem .7rem; background: #FFFFFF; }}
</style>
"""


@st.cache_resource
def client() -> ApiClient:
    return ApiClient(API_URL, os.getenv("OPERATOR_TOKEN") or None)


def local_time(iso: str) -> str:
    """HH:MM:SS on this machine's clock, like the chart axes (the API speaks UTC)."""
    return datetime.fromisoformat(iso).astimezone().strftime("%H:%M:%S")


def eyebrow(text: str, where: Any = st) -> None:  # Any: st or st.sidebar
    """A small uppercase section label."""
    where.markdown(f'<div class="eyebrow">{html.escape(text)}</div>', unsafe_allow_html=True)


def frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Chart data (a DataFrame: typed, unlike altair's inline Data)."""
    return pd.DataFrame(rows)


def campus_zones() -> list[dict[str, Any]]:
    """Zone rectangles from the campus layout file (static layout, not live state)."""
    raw = yaml.safe_load((ROOT / "config" / "campus_v1.yaml").read_text())
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


def campus_map(topology: dict[str, Any]) -> Any:  # Any: altair charts are partly untyped
    """The floor plan as a channel map: rings in each AP's channel colour, disc = load."""
    aps, stations = map_layers(topology)
    x = alt.X("x:Q", scale=alt.Scale(domain=[0, CAMPUS_W]), axis=None)
    y = alt.Y("y:Q", scale=alt.Scale(domain=[0, CAMPUS_H]), axis=None)
    ring_size = 3.1416 * (COVERAGE_M * MAP_W / CAMPUS_W) ** 2
    channel = alt.Color(
        "channel:N", scale=CHANNEL_SCALE, legend=alt.Legend(title="Channel", orient="right")
    )
    # every layer shares the axis-less x and y: one layer with default axes makes Vega fail to
    # merge the axes ("Cannot read properties of undefined (reading 'forEach')", found in P6.2)
    zones = alt.Chart(frame(campus_zones()))
    zone_box = zones.mark_rect(fill=None, stroke=GRID, strokeWidth=1).encode(
        x=x, x2="x2:Q", y=y, y2="y2:Q"
    )
    top = alt.Y("y2:Q", scale=alt.Scale(domain=[0, CAMPUS_H]), axis=None)
    zone_name = zones.mark_text(align="left", baseline="top", dx=6, dy=6, color=MUTED).encode(
        x=x, y=top, text="zone:N"
    )
    up = alt.Chart(frame([a for a in aps if a["band"] != "down"]))
    rings = up.mark_point(
        shape="circle", filled=False, size=ring_size, strokeWidth=2.5, opacity=0.9, clip=True
    ).encode(
        x=x,
        y=y,
        color=channel,
        strokeDash=alt.StrokeDash(
            "channel:N",
            scale=alt.Scale(domain=list(DASHES), range=list(DASHES.values())),
            legend=None,
        ),
    )
    station_layer = (
        alt.Chart(frame(stations))
        .mark_point(filled=True, size=42)
        .encode(
            x=x,
            y=y,
            shape=alt.condition(alt.datum.ap == "no AP", alt.value("cross"), alt.value("circle")),
            color=alt.condition(alt.datum.ap == "no AP", alt.value(CRITICAL), alt.value(MUTED)),
            tooltip=[alt.Tooltip("name:N", title="station"), alt.Tooltip("ap:N", title="on")],
        )
    )
    discs = (
        alt.Chart(frame(aps))
        .mark_point(shape="circle", filled=True, size=900, strokeWidth=3)
        .encode(
            x=x,
            y=y,
            fill=alt.Fill(
                "band:N",
                scale=alt.Scale(domain=list(LOAD), range=list(LOAD.values())),
                legend=alt.Legend(title="Load", orient="right"),
            ),
            stroke=channel,
            tooltip=["label:N", alt.Tooltip("shares_channel_with:N", title="shares airtime with")],
        )
    )
    labels = (
        alt.Chart(frame(aps))
        .mark_text(dy=-26, fontSize=12, fontWeight=600, font="IBM Plex Mono", color=INK)
        .encode(x=x, y=y, text="label:N")
    )
    return (
        alt.layer(zone_box, zone_name, rings, station_layer, discs, labels)
        .properties(width=MAP_W, height=MAP_H, background=PAPER)
        .configure_view(strokeWidth=0)
    )


def load_chart(series: list[dict[str, Any]]) -> Any:  # Any: as campus_map
    """Utilisation of each AP over the last 5 minutes, one panel per AP, one shared axis."""
    base = alt.Chart(frame(series))
    line = base.mark_line(strokeWidth=2).encode(
        x=alt.X("t:T", title=None, axis=alt.Axis(format="%H:%M:%S", labelColor=MUTED)),
        y=alt.Y(
            "util:Q", title="load", scale=alt.Scale(domain=[0, 1.05]), axis=alt.Axis(format="%")
        ),
        color=alt.Color("channel:N", scale=CHANNEL_SCALE, legend=None),
        tooltip=[
            "ap:N",
            alt.Tooltip("t:T", format="%H:%M:%S"),
            alt.Tooltip("util:Q", format=".0%"),
        ],
    )
    congested = base.mark_rule(strokeDash=[4, 3], color=CRITICAL).encode(y=alt.datum(CONGESTED))
    return (
        alt.layer(line, congested)
        .properties(width=170, height=120)
        .facet(column=alt.Column("ap:N", title=None))
    )


def kpi_chart(rows: list[dict[str, Any]]) -> Any:  # Any: as campus_map
    """Throughput, latency and loss of each traffic class over time; one panel per KPI."""
    line = (
        alt.Chart(frame(rows))
        .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=20))
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
    return (
        line.properties(width=230, height=130)
        .facet(column=alt.Column("kpi:N", title=None, sort=[label for label, _ in KPIS]))
        .resolve_scale(y="independent")
    )


@st.fragment(run_every=KPI_REFRESH)
def kpis() -> None:
    """The flows' measured KPIs per traffic class over the last 5 minutes (P1.5 probes)."""
    eyebrow("Traffic KPIs per class · last 5 minutes · mean over 10 s")
    api = client()
    try:
        points = {
            (c, field): api.get(f"/metrics?entity={c}&metric={field}&window=300")["points"]
            for c in CLASSES
            for _, field in KPIS
        }
    except ApiError as exc:
        st.caption(str(exc))
        return
    rows = kpi_series(points)
    if rows:
        st.altair_chart(kpi_chart(rows))
    else:
        st.markdown("No flow measured yet. The probes report once the scenario's traffic starts.")


def twin_chart(rows: list[dict[str, Any]]) -> Any:  # Any: as campus_map
    """Before, twin predicted and measured for each watched action; one panel per KPI."""
    sources = ["before", "twin predicted", "measured"]
    bars = (
        alt.Chart(frame(rows))
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            y=alt.Y("source:N", sort=sources, title=None),
            x=alt.X("value:Q", title=None),
            color=alt.Color(
                "source:N",
                scale=alt.Scale(domain=sources, range=[GRID, "#2F5FD0", INK]),
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
    return (
        bars.properties(width=190, height=70)
        .facet(
            # the action reads horizontally above its row (rotated labels overlapped, P6.2)
            row=alt.Row(
                "what:N",
                title=None,
                header=alt.Header(
                    labelAngle=0, labelAlign="left", labelOrient="top", labelFont="IBM Plex Mono"
                ),
            ),
            column=alt.Column("kpi:N", title=None),
        )
        .resolve_scale(x="independent")
    )


def metric_series(api: ApiClient, aps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for a in aps:
        points = api.get(f"/metrics?entity={a['name']}&metric=channel_util&window=300")["points"]
        rows += [
            {"ap": a["name"], "channel": f"ch {a['channel']}", "t": p["ts"], "util": p["value"]}
            for p in points
        ]
    return rows


def decide(action_id: str, step: str) -> None:
    try:
        client().operator(action_id, step, by=OPERATOR)
        st.toast(f"{action_id}: {'applied' if step == 'apply' else step + 'd'}")
    except ApiError as exc:
        st.toast(str(exc))


@st.fragment(run_every=REFRESH)
def live() -> None:
    """Everything that follows the network; re-drawn every few seconds."""
    api = client()
    try:
        actions = api.get("/actions")["actions"]
    except ApiError as exc:
        st.error(str(exc))
        return
    try:  # 503 before the run's first telemetry: the queue and alerts still show
        topology: dict[str, Any] | None = api.get("/topology")
    except ApiError as exc:
        topology, no_state = None, str(exc)
    try:
        alerts = api.get("/alerts?since=600")["alerts"]
    except ApiError:
        alerts = []
    left, right = st.columns([3, 2], gap="large")
    with left:
        if topology is None:
            eyebrow("Campus")
            st.info(no_state)
        else:
            eyebrow(f"Campus · twin state at {local_time(topology['ts'])}")
            st.altair_chart(campus_map(topology), width="content")
            st.caption(MAP_KEY)
    with right:
        decisions(actions, alerts)
    if "rca" in st.session_state:
        alert, report = st.session_state["rca"]
        with st.expander(
            f"Root cause · {alert['entity']} at {local_time(alert['ts'])}", expanded=True
        ):
            show_report(report)
    charts(api, topology, actions)


MAP_KEY = (
    f"Rings: {COVERAGE_M:.0f} m coverage (RSSI at least -75 dBm), coloured by channel; rings of"
    " one colour overlapping = APs sharing airtime. Disc: load ("
    + ", ".join(f"{b.name} {b.meaning}" for b in BANDS)
    + "). ✕ = station without an AP."
)


def decisions(actions: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> None:
    """What waits for the operator, the newest alerts, and what the system did lately."""
    eyebrow("Waiting for you")
    queue = decision_queue(actions)
    if not queue:
        st.markdown("Nothing needs a decision. High-impact changes wait here before they apply.")
    for item in queue:
        # every field is escaped: the reason and parameters can be written by the LLM (L-6)
        e = {k: html.escape(str(v)) for k, v in item.items()}
        st.markdown(
            f'<div class="card {e["impact"]}"><div class="what">{e["what"]}</div>'
            f'<div>{e["why"]}</div><div class="twin">twin: {e["twin"]}'
            f" · {e['impact']} impact · from {e['source']}</div></div>",
            unsafe_allow_html=True,
        )
        go, no = st.columns(2)
        label = "Approve" if item["next_step"] == "approve" else "Apply now"
        step, action_id = item["next_step"], item["action_id"]
        go.button(label, key=f"go-{action_id}", on_click=decide, args=(action_id, step))
        no.button("Deny", key=f"no-{action_id}", on_click=decide, args=(action_id, "deny"))
    eyebrow("Alerts · last 10 minutes")
    if not alerts:
        st.markdown("No anomaly in the last 10 minutes.")
    for alert in reversed(alerts[-3:]):
        st.markdown(
            f'<div class="alert"><span class="mono">{local_time(alert["ts"])}</span> · '
            f"<b>{html.escape(alert['entity'])}</b> looks unusual"
            f" · score {alert['score']:.2f}</div>",
            unsafe_allow_html=True,
        )
        if st.button("Explain this alert", key=f"rca-{alert['ts']}"):
            st.session_state["rca"] = (alert, explain(alert))
    done = ("kept", "rolled_back", "applied", "denied")
    recent = [a for a in actions if a["status"] in done][-5:]
    eyebrow("Recent actions")
    for a in reversed(recent):
        st.markdown(
            f'<span class="mono">{a["status"]:<11}</span> {html.escape(describe(a["action"]))}',
            unsafe_allow_html=True,
        )


def charts(api: ApiClient, topology: dict[str, Any] | None, actions: list[dict[str, Any]]) -> None:
    """Load over time (once the twin has a state) and the twin's predictions next to what was
    measured."""
    if topology is not None:
        eyebrow("Load per AP · last 5 minutes")
        try:
            st.altair_chart(load_chart(metric_series(api, topology["aps"])))
        except ApiError as exc:
            st.caption(str(exc))
    eyebrow("Twin prediction vs what happened")
    rows = twin_vs_live(actions)
    if rows:
        st.altair_chart(twin_chart(rows))
    else:
        st.markdown(
            "No action has finished its 30 s watch yet. Each one will show the twin's prediction"
            " next to what was measured."
        )


def explain(alert: dict[str, Any]) -> dict[str, Any]:
    with st.spinner("Asking the root-cause explainer…"):
        try:
            report: dict[str, Any] = client().post("/alerts/explain", {"alert": alert})
        except ApiError as exc:
            return {"error": str(exc)}
    return report


def show_report(report: dict[str, Any]) -> None:
    if "error" in report:
        st.error(report["error"])
        return
    st.markdown(f"**{report['summary']}**")
    for c in report["likely_causes"]:
        st.markdown(
            f"- `{c['category']}` on **{c['entity']}** ({c['confidence']:.0%}): {c['evidence']}"
        )
    for s in report["suggested_actions"]:
        st.markdown(f"- suggested `{describe(s['action'])}` · twin {verdict_word(s['verdict'])}")
    st.caption(f"model {report.get('model', '?')} · evidence from the last 5 minutes")


def sidebar() -> None:
    api = client()
    eyebrow("Ask the network", st.sidebar)
    history = st.session_state.setdefault("chat", [])
    for question, reply in history[-3:]:
        st.sidebar.markdown(f"**You:** {question}")
        st.sidebar.markdown(reply.get("answer") or reply.get("error", ""))
        for s in reply.get("suggested_actions", []):
            st.sidebar.caption(
                f"suggested {describe(s['action'])} · twin {verdict_word(s['verdict'])}"
            )
    question = st.sidebar.chat_input("Why is video slow in the lecture hall?")
    if question:
        with st.sidebar, st.spinner("The copilot is looking at the network…"):
            try:
                reply = api.post("/chat", {"question": question})
            except ApiError as exc:
                reply = {"error": str(exc)}
        history.append((question, reply))
        st.rerun()
    eyebrow("Tell the network what you want", st.sidebar)
    with st.sidebar.form("intent", clear_on_submit=True):
        text = st.text_input(
            "Intent",
            placeholder="Give video calls in the lecture hall priority.",
            label_visibility="collapsed",
        )
        if st.form_submit_button("Send intent") and text:
            try:
                result = api.post("/intents", {"text": text})
            except ApiError as exc:
                st.error(str(exc))
                return
            if result["error"]:
                st.error(result["error"])
            for a in result["actions"]:
                st.markdown(
                    f"`{describe(a)}` · twin {verdict_word(result['verdicts'][a['action_id']])}"
                )


def main() -> None:
    st.set_page_config(page_title="Campus Wi-Fi twin", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    eyebrow("GenAI-driven digital twin · SDN Wi-Fi")
    st.title("Campus Wi-Fi twin")
    sidebar()
    live()
    kpis()


if __name__ == "__main__":  # `streamlit run` executes this file as __main__
    main()
