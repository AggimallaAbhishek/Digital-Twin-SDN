"""The dashboard's other pages: network map, digital twin, AI copilot, policies, history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.cards import bubble, event_card, floor_plan, intent_body, measured, twin_card
from dashboard.client import ApiClient, ApiError
from dashboard.copilot import copilot_card
from dashboard.data import (
    ALERTS_S,
    CHART_REFRESH,
    CLASSES,
    LLM_INTENT_SOURCE,
    RCA_WINDOW_MIN,
    REFRESH,
    WINDOW_S,
    ap_names,
    client,
    demo_start,
    live,
)
from dashboard.panels import (
    clock_label,
    intent_view,
    source_word,
    status_word,
)
from dashboard.theme import INDIGO, LINE, MUTED, NAVY, RED, WHITE
from dashboard.ui import card, html, table, table_row
from dashboard.views import (
    CONGESTED,
    KPIS,
    AlertGroup,
    alert_groups,
    counted,
    kpi_series,
    map_layers,
    plain_action,
    rca_view,
    reason,
    rich_html,
    safe_html,
    verdict_word,
)


@st.fragment(run_every=REFRESH)
def network_live() -> None:
    """The floor plan and the AP table (refreshed every few seconds)."""
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


def network_map() -> None:
    """The Network map page: the live plan and table, then the charts on their own slower
    refresh (a fragment inside another would rerun with it, every few seconds)."""
    network_live()
    charts()


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
    """An Altair chart in the page's look: white card, navy ink, light guide lines."""
    return (
        chart.configure(background=WHITE, font="Hanken Grotesk")
        .configure_view(stroke=None)
        .configure_axis(labelColor=MUTED, gridColor=LINE, domainColor=NAVY, tickColor=NAVY)
        .configure_header(labelColor=NAVY, labelFontWeight="bold", labelFontSize=13)
        .configure_legend(labelColor=NAVY, titleColor=NAVY)
    )


def load_chart(api: ApiClient) -> None:
    """Load per AP over the chart window, one small chart each, the congestion line in red."""
    html(f"<h3>Load per AP · last {WINDOW_S // 60} minutes</h3>")
    rows = []
    for name in ap_names():  # the campus layout: no second /topology read
        points = api.get(f"/metrics?entity={name}&metric=channel_util&window={WINDOW_S}")["points"]
        rows += [{"ap": name, "t": p["ts"], "util": p["value"]} for p in points]
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
    """Throughput, latency and loss per traffic class over the chart window."""
    html(f"<h3>Traffic per class · last {WINDOW_S // 60} minutes</h3>")
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
    start = demo_start()
    html(
        card("Every twin check", verdict_table(list(snap.actions), start, "No change checked yet."))
    )


def verdict_row(r: dict[str, Any], start: datetime | None) -> str:
    """One twin check as a table row: when, what, from whom, the verdict and its numbers."""
    v = r["verdict"]
    p = v.get("predicted") or {}
    if not v.get("accepted"):
        detail = reason(v)
    elif p:
        detail = f"{p.get('latency_ms', 0):.0f} ms · {p.get('loss_pct', 0):.1f}%"
    else:
        detail = "—"
    return table_row(
        safe_html(clock_label(r["action"]["created_at"], start)),
        safe_html(plain_action(r["action"])),
        safe_html(source_word(r)),
        f"<b>{safe_html(verdict_word(v))}</b>",
        safe_html(detail),
        safe_html(status_word(r)),
    )


def copilot_page() -> None:
    """The AI copilot page: the whole conversation beside the alerts and their root cause."""
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
        groups = alert_groups(snap.alerts) if snap else []
        if not groups:
            html(f'<p class="empty">No anomaly alert in the last {ALERTS_S // 60} minutes.</p>')
        start = demo_start()
        reports: dict[str, Any] = st.session_state.setdefault("rca", {})
        for g in groups[:6]:
            when = safe_html(clock_label(g.first, start))
            html(
                f'<div class="ev"><div class="t coral">{when}</div>'
                f"<div><b>{safe_html(g.entity)} looks unusual</b>"
                f"<span>{counted(g.count, 'alert')}</span></div></div>"
            )
            explain(g, reports)


def explain(group: AlertGroup, reports: dict[str, Any]) -> None:
    """The root-cause report of an alert episode, or the button that asks for it."""
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
        f'<div class="tools">by {safe_html(view.model)} · evidence from the '
        f"{RCA_WINDOW_MIN} minutes before the alert</div>"
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
            intent_body(intent_view(c["reply"]))
            + ('<div class="ok">✓ applied</div>' if c["applied"] else ""),
        )
        for c in reversed(intents)
    )
    none = '<p class="empty">No intent sent yet. Use the copilot box on the Overview page.</p>'
    html(card("Intents this session", items or none, "lavender", spaced=False))
    snap = live()
    if snap is None:
        return
    start = demo_start()
    ai = [r for r in snap.actions if r["action"].get("source") == LLM_INTENT_SOURCE]
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
    start = demo_start()
    html(event_card(snap, start, limit=40))
    ledger = "".join(
        table_row(
            safe_html(clock_label(r["action"]["created_at"], start)),
            f"<code>{safe_html(r['action_id'])}</code>",
            safe_html(plain_action(r["action"])),
            safe_html(source_word(r)),
            safe_html(verdict_word(r["verdict"])),
            safe_html(status_word(r)),
            safe_html(measured_words(r)),
            safe_html(r.get("note") or ""),
        )
        for r in sorted(snap.actions, key=lambda r: r["action"]["created_at"], reverse=True)
    )
    head = ("Time", "Id", "Change", "From", "Twin", "Status", "Measured", "Note")
    empty = "Empty: no change recorded in this run."
    html(card("Action ledger", table(head, ledger, empty)))
    alerts = "".join(
        table_row(
            safe_html(clock_label(a["ts"], start)),
            safe_html(a["entity"]),
            f"{a['score']:.2f}",
            safe_html(a.get("detector", "")),
        )
        for a in sorted(snap.alerts, key=lambda a: a["ts"], reverse=True)
    )
    empty = f"No anomaly alert in the last {ALERTS_S // 60} minutes."
    html(card("Alerts", table(("Time", "Entity", "Score", "Detector"), alerts, empty)))


def measured_words(record: dict[str, Any]) -> str:
    """What the watch measured, in one line; "—" before (or without) a watch."""
    m = record.get("measured")
    if not m:
        return "—"
    return f"{m['latency_ms']:.0f} ms · {m['loss_pct']:.1f}% · {m['throughput_mbps']:.2f} Mbit/s"
