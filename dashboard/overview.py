"""The dashboard's header, story strip and the Overview page."""

from __future__ import annotations

import math
from datetime import datetime

import streamlit as st

from dashboard.cards import ap_card, event_card, floor_plan, twin_card
from dashboard.client import ApiError
from dashboard.copilot import copilot_card, proposal_card
from dashboard.data import (
    MAX_LOOKBACK_S,
    REFRESH,
    ap_names,
    campus,
    client,
    demo,
    demo_start,
    live,
    now,
    read_live,
    stories,
    watch,
)
from dashboard.panels import (
    DemoClock,
    Live,
    congestion_onset,
    focus_ap,
    hero,
    story_steps,
)
from dashboard.theme import NAVY
from dashboard.ui import html
from dashboard.views import md_literal, safe_html

WIFI_ICON = (
    f'<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="{NAVY}" '
    'stroke-width="2.6" stroke-linecap="round" aria-hidden="true">'
    '<path d="M2.5 9a14 14 0 0 1 19 0"/>'
    '<path d="M6 12.6a9 9 0 0 1 12 0"/><path d="M9.5 16.2a4 4 0 0 1 5 0"/>'
    f'<circle cx="12" cy="19.5" r="1.4" fill="{NAVY}" stroke="none"/></svg>'
)

# ---------------------------------------------------------------- header and story strip


@st.fragment(run_every=REFRESH)
def header() -> None:
    """The four header cells: the name, the scenario, the demo clock and the live status."""
    snap, clock = live(), demo()
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


def onset_s(clock: DemoClock) -> float | None:
    """When an AP was first congested in this run, from the APs' load history (GET /metrics):
    the twin state only knows now. The look-back is rounded up to 30 s so a refresh reuses
    the cached answer."""
    window = min(MAX_LOOKBACK_S, 30 * math.ceil((clock.elapsed_s + 5) / 30))
    return _onset(clock.start.isoformat(), window)


@st.cache_data(ttl=15, show_spinner=False)
def _onset(start: str, window_s: int) -> float | None:
    try:
        series = {
            ap: client().get(f"/metrics?entity={ap}&metric=channel_util&window={window_s}")[
                "points"
            ]
            for ap in ap_names()
        }
    except ApiError:
        return None
    return congestion_onset(series, datetime.fromisoformat(start))


def story_strip(snap: Live, clock: DemoClock | None) -> None:
    """The six steps of the demo's story (only while a demo with a story plays)."""
    story = stories().get(clock.scenario, []) if clock else []
    if not story or clock is None:
        return
    steps = story_steps(story, clock, snap, watch(), onset_s(clock))
    html(
        '<div class="steps">'
        + "".join(
            f'<div class="step {s.state}"><b>{i} {safe_html(s.label)}</b>'
            f"<span>{safe_html(s.sub)}</span></div>"
            for i, s in enumerate(steps, start=1)
        )
        + "</div>"
    )


def hero_row(snap: Live, start: datetime | None) -> None:
    """The status card and the three big numbers of the AP it names (panels.focus_ap)."""
    zones = campus()
    card = hero(snap, zones, start)
    focus = focus_ap(snap.topology)
    if focus is None:
        tiles = [("—", "Clients"), ("—", "Load"), ("—", "Packet loss")]
    else:
        loss = "—" if focus.loss_pct is None else f"{focus.loss_pct:.1f}%"
        tiles = [
            (str(focus.clients), f"Clients on {focus.name}"),
            (f"{focus.util:.0%}" if focus.up else "off", f"Load on {focus.name}"),
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


# ---------------------------------------------------------------- the Overview page


@st.fragment(run_every=REFRESH)
def overview_top() -> None:
    """Story strip and the hero row (refreshed every few seconds)."""
    snap, clock = live(), demo()
    if snap is None:
        st.error(f"{md_literal(read_live().get('error', ''))} · this page reconnects by itself.")
        return
    story_strip(snap, clock)
    hero_row(snap, clock.start if clock else None)


@st.fragment(run_every=REFRESH)
def sheet() -> None:
    """The floor plan sheet (refreshed every few seconds)."""
    snap = live()
    if snap is not None:
        floor_plan(snap)


@st.fragment(run_every=REFRESH)
def proposal() -> None:
    """The proposal card (refreshed every few seconds)."""
    snap = live()
    if snap is not None:
        proposal_card(snap, demo_start())


@st.fragment(run_every=REFRESH)
def bottom_row() -> None:
    """Access points, event timeline and twin vs measured (refreshed every few seconds)."""
    snap = live()
    if snap is None:
        return
    start = demo_start()
    cols = st.columns(3, gap="medium")
    html(ap_card(snap), cols[0])
    html(event_card(snap, start), cols[1])
    html(twin_card(snap), cols[2])


def overview() -> None:
    """The Overview page, laid out as the design image."""
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
