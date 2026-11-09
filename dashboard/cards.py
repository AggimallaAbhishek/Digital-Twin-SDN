"""The cards several dashboard pages show: the floor plan, access points, the event timeline,
twin against measured, and the copilot's bubbles."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from dashboard.data import campus, watch, watch_s
from dashboard.panels import (
    IntentView,
    Live,
    ap_rows,
    event_rows,
    map_move,
    status_word,
)
from dashboard.svg import floor_plan_svg, twin_bars_svg
from dashboard.theme import CORAL, INDIGO, LAVENDER, NAVY, RED, WHITE
from dashboard.ui import card, html
from dashboard.views import (
    map_layers,
    plain_action,
    safe_html,
)


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


def intent_body(view: IntentView) -> str:
    """An intent's reply: its changes in words, then the twin's check (✓ passed, ✕ refused)."""
    check = ""
    if view.check:
        css, mark = ("ok", "✓") if view.ok else ("no", "✕")
        check = f'<div class="{css}">{mark} {safe_html(view.check)}</div>'
    return safe_html(view.text) + check


def bubble(chip: str, body: str) -> str:
    """An AI-written reply: a white bubble marked with what it answers (body escaped)."""
    return f'<div class="bubble"><span class="chip">{chip}</span><br>{body}</div>'


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


def event_card(snap: Live, start: datetime | None, limit: int = 6) -> str:
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
    f'<div class="keys"><span><i style="background:{CORAL}"></i>Before</span>'
    f'<span><i style="background:{LAVENDER};border-style:dashed"></i>Twin predicted</span>'
    f'<span><i style="background:{INDIGO}"></i>Measured live</span></div>'
)


def measured(actions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The changes whose watch measured the network, newest first."""
    done = [r for r in actions if r.get("measured") and r["applied_at"]]
    return sorted(done, key=lambda r: r["applied_at"], reverse=True)


def twin_card(snap: Live, record: dict[str, Any] | None = None) -> str:
    """Before / twin predicted / measured for the newest measured change, or for `record`
    (then titled by the change itself: the Digital twin page shows several side by side)."""
    title = "Twin prediction against measured"
    if record is None:
        newest = measured(snap.actions)
        record = newest[0] if newest else None
    else:
        title = plain_action(record["action"])
    if record is None:
        body = (
            f'<p class="empty">No change has finished its {watch_s()} s watch yet. Each '
            "one will show the twin's prediction next to what was measured.</p>"
        )
        return card(title, body, spaced=False)
    v = record["verdict"]
    bars = twin_bars_svg(v["baseline"], v["predicted"], record["measured"])
    outcome = status_word(record)
    what = (
        f'<p class="empty">{safe_html(plain_action(record["action"]))} · {safe_html(outcome)}</p>'
    )
    return card(title, TWIN_KEYS + bars + what, spaced=False)
