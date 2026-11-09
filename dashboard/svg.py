"""Blueprint + Sorbet SVGs (design §4.4, §4.7): the campus floor plan and the twin-vs-measured
bars, as inline SVG markup. Pure functions, no Streamlit (tests/unit/test_dashboard_svg.py).

Every name or label that came from the API is escaped before it goes into the markup (rule L-6):
an AP or station name is text, never markup.
"""

from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dashboard.theme import (
    CORAL,
    CORAL_HATCH,
    CORAL_ZONE,
    GREY_ZONE,
    INDIGO,
    LAVENDER,
    LINE,
    NAVY,
    OTHER_ZONE,
    PANEL,
    RED,
    RULE,
    WHITE,
    YELLOW,
    ZONE_COLOURS,
)
from dashboard.views import counted

Row = dict[str, Any]  # Any: JSON values (map_layers rows)

PX_PER_M = 10.0
PAD_LEFT, PAD_TOP, PAD_RIGHT, PAD_BOTTOM = 52.0, 14.0, 14.0, 48.0
ZONE_INSET_M = 0.8  # the gutter between zones, as in the design
AP_R = 17.0  # px: an AP disc, about twice a client dot (clients are drawn over it)
PILL_W, PILL_H = 44.0, 18.0  # px: the channel pill under an AP ("ch 11" fits)
CLIENT_R = 8.0
RING_SHARE = 0.82  # the coverage ring: this share of the zone's half-size (true 30 m leaves it)
DISC_FILL = {"calm": WHITE, "busy": YELLOW, "congested": RED, "down": GREY_ZONE}


@dataclass(frozen=True)
class Move:
    """A client steer to draw: proposed (waiting or verified) or moving (applied, watched)."""

    from_ap: str
    to_ap: str
    stations: tuple[str, ...]
    state: str  # "proposed" or "moving"

    def label(self) -> str:
        """The words on the move line: "Move 3 clients to ap3"."""
        n = len(self.stations)
        verb = "Moving" if self.state == "moving" else "Move"
        return f"{verb} {counted(n, 'client')} to {self.to_ap}"


def _e(value: object) -> str:
    """Text or an attribute value from the API, escaped for SVG markup."""
    return html.escape(str(value), quote=True)


def _f(value: float) -> str:
    return f"{value:.1f}"


class _Plan:
    """Metres on the floor plan to px in the SVG (y up in metres, down in px). The plan is the
    zones' bounding box: what is drawn, so its dimension lines say what they measure."""

    def __init__(self, zones: Sequence[Row]) -> None:
        self.x0 = float(min(z["x"] for z in zones))
        self.x1 = float(max(z["x2"] for z in zones))
        self.y0 = float(min(z["y"] for z in zones))
        self.y1 = float(max(z["y2"] for z in zones))
        self.w_m, self.h_m = self.x1 - self.x0, self.y1 - self.y0
        self.width = PAD_LEFT + self.w_m * PX_PER_M + PAD_RIGHT
        self.height = PAD_TOP + self.h_m * PX_PER_M + PAD_BOTTOM

    def x(self, x_m: float) -> float:
        return PAD_LEFT + (x_m - self.x0) * PX_PER_M

    def y(self, y_m: float) -> float:
        return PAD_TOP + (self.y1 - y_m) * PX_PER_M


def in_zone(zone: Row, x: float, y: float) -> bool:
    """True when (x, y) is in `zone`'s rectangle; edges count as inside, like the twin's
    zone_of (which the dashboard may not import)."""
    return bool(zone["x"] <= x <= zone["x2"] and zone["y"] <= y <= zone["y2"])


def zone_title(name: str) -> str:
    """A zone's name as a label: "lecture hall" -> "Lecture hall"."""
    return name[:1].upper() + name[1:]


def _zone_ap(zone: Row, aps: Sequence[Row]) -> Row | None:
    """The AP standing in `zone`, if any."""
    return next((a for a in aps if in_zone(zone, a["x"], a["y"])), None)


def floor_plan_svg(
    aps: Sequence[Row],
    stations: Sequence[Row],
    zones: Sequence[Row],
    move: Move | None = None,
) -> str:
    """The campus floor plan: zones in their sorbet colour (hatched coral when their AP is
    congested, grey when it is down), AP discs with channel pills, coverage rings, the clients
    (red on a congested AP, dashed while moved, ✕ without an AP) and a dashed move line."""
    plan = _Plan(zones)
    by_name = {a["name"]: a for a in aps}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" class="plan" role="img" '
        f'aria-label="Campus floor plan" viewBox="0 0 {_f(plan.width)} {_f(plan.height)}">',
        _defs(),
        f'<rect x="{_f(plan.x(plan.x0))}" y="{_f(plan.y(plan.y1))}" '
        f'width="{_f(plan.w_m * PX_PER_M)}" '
        f'height="{_f(plan.h_m * PX_PER_M)}" fill="none" stroke="{RULE}" stroke-width="1.5"/>',
    ]
    zoned = [(z, _zone_ap(z, aps)) for z in zones]
    parts += [_zone(plan, z, ap) for z, ap in zoned]
    for z, ap in zoned:  # rings over every zone fill, under the clients
        if ap is not None and ap["band"] != "down":
            half = min(z["x2"] - z["x"], z["y2"] - z["y"]) / 2 * RING_SHARE * PX_PER_M
            parts.append(
                f'<circle cx="{_f(plan.x(ap["x"]))}" cy="{_f(plan.y(ap["y"]))}" r="{_f(half)}" '
                f'fill="none" stroke="{NAVY}" stroke-opacity=".6" stroke-width="1.5" '
                f'stroke-dasharray="5 5"/>'
            )
    line, label = _move(plan, move, by_name)
    parts.append(line)
    parts += [_ap(plan, a) for a in aps]
    parts += [_client(plan, s, by_name, move) for s in stations]  # over the discs: never hidden
    parts.append(label)
    parts.append(_dimensions(plan))
    parts.append("</svg>")
    return "".join(parts)


def _defs() -> str:
    return (
        "<defs>"
        '<pattern id="hatch" patternUnits="userSpaceOnUse" width="18" height="18" '
        'patternTransform="rotate(45)">'
        f'<rect width="18" height="18" fill="{CORAL_ZONE}"/>'
        f'<rect width="7" height="18" fill="{CORAL_HATCH}"/></pattern>'
        '<radialGradient id="glow">'
        f'<stop offset="0" stop-color="{RED}" stop-opacity=".45"/>'
        f'<stop offset="1" stop-color="{RED}" stop-opacity="0"/></radialGradient>'
        "</defs>"
    )


def _zone(plan: _Plan, z: Row, ap: Row | None) -> str:
    state = ap["band"] if ap is not None else "none"
    fill = {"congested": "url(#hatch)", "down": GREY_ZONE}.get(
        state, ZONE_COLOURS.get(z["zone"], OTHER_ZONE)
    )
    x, y = plan.x(z["x"] + ZONE_INSET_M), plan.y(z["y2"] - ZONE_INSET_M)
    w = (z["x2"] - z["x"] - 2 * ZONE_INSET_M) * PX_PER_M
    h = (z["y2"] - z["y"] - 2 * ZONE_INSET_M) * PX_PER_M
    out = [
        f'<rect x="{_f(x + 5)}" y="{_f(y + 5)}" width="{_f(w)}" height="{_f(h)}" rx="10" '
        f'fill="{NAVY}"/>',
        f'<rect data-zone="{_e(z["zone"])}" data-state="{_e(state)}" x="{_f(x)}" y="{_f(y)}" '
        f'width="{_f(w)}" height="{_f(h)}" rx="10" fill="{fill}" stroke="{NAVY}" '
        'stroke-width="2"/>',
    ]
    if state == "congested" and ap is not None:
        r = min(w, h) * 0.46
        out.append(
            f'<circle cx="{_f(plan.x(ap["x"]))}" cy="{_f(plan.y(ap["y"]))}" r="{_f(r)}" '
            f'fill="url(#glow)"/>'
        )
    # the name at the zone's outer corner: left or right, top or bottom of the campus
    left = (z["x"] + z["x2"]) / 2 <= (plan.x0 + plan.x1) / 2
    top = (z["y"] + z["y2"]) / 2 >= (plan.y0 + plan.y1) / 2
    tx = x + 16 if left else x + w - 16
    ty = y + 30 if top else y + h - 16
    name = str(z["zone"])
    out.append(
        f'<text class="disp" x="{_f(tx)}" y="{_f(ty)}" font-size="20" fill="{NAVY}" '
        f'text-anchor="{"start" if left else "end"}">{_e(zone_title(name))}</text>'
    )
    return "".join(out)


def _client(plan: _Plan, s: Row, aps: Mapping[str, Row], move: Move | None) -> str:
    cx, cy = plan.x(s["x"]), plan.y(s["y"])
    name = _e(s["name"])
    ap = s.get("ap")
    if not ap or ap == "no AP":  # map_layers writes "no AP"
        d = CLIENT_R
        return (
            f'<g data-client="{name}" class="client lost" stroke="{RED}" stroke-width="4" '
            f'stroke-linecap="round"><title>{name}: no access point</title>'
            f'<line x1="{_f(cx - d)}" y1="{_f(cy - d)}" x2="{_f(cx + d)}" y2="{_f(cy + d)}"/>'
            f'<line x1="{_f(cx - d)}" y1="{_f(cy + d)}" x2="{_f(cx + d)}" y2="{_f(cy - d)}"/></g>'
        )
    if move is not None and s["name"] in move.stations:
        kind, fill, dash = "client moving", WHITE, ' stroke-dasharray="3 2.5"'
    elif aps.get(ap, {}).get("band") == "congested":
        kind, fill, dash = "client hot", RED, ""
    else:
        kind, fill, dash = "client", INDIGO, ""
    return (
        f'<circle data-client="{name}" class="{kind}" cx="{_f(cx)}" cy="{_f(cy)}" '
        f'r="{_f(CLIENT_R)}" fill="{fill}" stroke="{NAVY}" stroke-width="2.5"{dash}>'
        f"<title>{name} on {_e(ap)}</title></circle>"
    )


def _ap(plan: _Plan, a: Row) -> str:
    cx, cy = plan.x(a["x"]), plan.y(a["y"])
    band = a["band"]
    dash = ' stroke-dasharray="6 4"' if band == "down" else ""
    ink = WHITE if band == "congested" else NAVY
    pill_w, pill_h, pill_y = PILL_W, PILL_H, cy + AP_R + 5
    channel = "off" if band == "down" else a["channel"]
    name = _e(a["name"])
    return (
        f'<circle cx="{_f(cx + 3)}" cy="{_f(cy + 3)}" r="{_f(AP_R)}" fill="{NAVY}"/>'
        f'<circle data-ap="{name}" class="ap {_e(band)}" cx="{_f(cx)}" cy="{_f(cy)}" '
        f'r="{_f(AP_R)}" fill="{DISC_FILL.get(band, WHITE)}" stroke="{NAVY}" '
        f'stroke-width="2.5"{dash}>'
        f"<title>{name}: {_e(band)}</title></circle>"
        f'<text class="disp" x="{_f(cx)}" y="{_f(cy + 4.5)}" font-size="13" fill="{ink}" '
        f'text-anchor="middle">{name}</text>'
        f'<rect x="{_f(cx - pill_w / 2)}" y="{_f(pill_y)}" width="{_f(pill_w)}" '
        f'height="{_f(pill_h)}" rx="{_f(pill_h / 2)}" fill="{WHITE}" stroke="{NAVY}" '
        'stroke-width="1.5"/>'
        f'<text x="{_f(cx)}" y="{_f(pill_y + pill_h / 2 + 4)}" font-size="11" font-weight="700" '
        f'fill="{NAVY}" text-anchor="middle">{_e(channel)}</text>'
    )


def _move(plan: _Plan, move: Move | None, aps: Mapping[str, Row]) -> tuple[str, str]:
    """(the dashed line, its label pill): drawn apart so the line runs under the AP discs and
    the label sits over everything. Empty strings when there is nothing to draw."""
    if move is None or move.from_ap not in aps or move.to_ap not in aps:
        return "", ""
    src, dst = aps[move.from_ap], aps[move.to_ap]
    x1, y1, x2, y2 = plan.x(src["x"]), plan.y(src["y"]), plan.x(dst["x"]), plan.y(dst["y"])
    length = math.hypot(x2 - x1, y2 - y1)
    if length <= 2 * (AP_R + 6):
        return "", ""
    ux, uy = (x2 - x1) / length * (AP_R + 6), (y2 - y1) / length * (AP_R + 6)
    line = (
        f'<line class="move" x1="{_f(x1 + ux)}" y1="{_f(y1 + uy)}" x2="{_f(x2 - ux)}" '
        f'y2="{_f(y2 - uy)}" stroke="{NAVY}" stroke-width="3" stroke-dasharray="7 6"/>'
    )
    text = move.label()
    w, h = len(text) * 8.6 + 26, 32.0
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    steep = abs(y2 - y1) >= abs(x2 - x1)
    lx = mx + 12 if steep else mx - w / 2  # beside a steep line, above a flat one
    ly = my - h / 2 if steep else my - h - 10
    label = (
        f'<rect x="{_f(lx)}" y="{_f(ly)}" width="{_f(w)}" height="{_f(h)}" rx="10" '
        f'fill="{NAVY}"/>'
        f'<text x="{_f(lx + w / 2)}" y="{_f(ly + 21)}" font-size="15" font-weight="700" '
        f'fill="{YELLOW}" text-anchor="middle">{_e(text)}</text>'
    )
    return line, label


def _dimensions(plan: _Plan) -> str:
    left = PAD_LEFT - 24
    top, bottom = plan.y(plan.y1), plan.y(plan.y0)
    base = bottom + 26
    mid_y, mid_x = (top + bottom) / 2, (plan.x(plan.x0) + plan.x(plan.x1)) / 2
    return (
        f'<line x1="{_f(left)}" y1="{_f(top)}" x2="{_f(left)}" y2="{_f(bottom)}" '
        f'stroke="{RULE}" stroke-width="1.5"/>'
        f'<text x="{_f(left + 5)}" y="{_f(mid_y)}" font-size="15" fill="{WHITE}" '
        f'text-anchor="middle" transform="rotate(-90 {_f(left - 4)} {_f(mid_y)})">'
        f"{_e(f'{plan.h_m:g} m')}</text>"
        f'<line x1="{_f(plan.x(plan.x0))}" y1="{_f(base)}" '
        f'x2="{_f(plan.x(plan.x1))}" y2="{_f(base)}" '
        f'stroke="{RULE}" stroke-width="1.5"/>'
        f'<rect x="{_f(mid_x - 30)}" y="{_f(base - 10)}" width="60" height="20" fill="{PANEL}"/>'
        f'<text x="{_f(mid_x)}" y="{_f(base + 5)}" font-size="15" fill="{WHITE}" '
        f'text-anchor="middle">{_e(f"{plan.w_m:g} m")}</text>'
    )


# ---------------------------------------------------------------- twin vs measured

BARS = (  # (field, group label, value format)
    ("latency_ms", "Latency (ms)", "{:.0f}"),
    ("loss_pct", "Packet loss (%)", "{:.1f}"),
)
SOURCES = (  # (key, fill, dashed)
    ("before", CORAL, False),
    ("predicted", LAVENDER, True),
    ("measured", INDIGO, False),
)
BAR_W, BAR_GAP, GROUP_W, GROUP_GAP = 52.0, 22.0, 236.0, 44.0
BAR_MAX_H, BASE_Y = 150.0, 214.0


def twin_bars_svg(
    before: Mapping[str, float], predicted: Mapping[str, float], measured: Mapping[str, float]
) -> str:
    """Before / twin predicted / measured live for latency and packet loss, one group each,
    every bar scaled to its group's tallest, with its value over it."""
    values = {"before": before, "predicted": predicted, "measured": measured}
    width = 2 * GROUP_W + GROUP_GAP + 8
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" class="bars" role="img" '
        f'aria-label="Twin prediction against measured" viewBox="0 0 {_f(width)} 262">'
    ]
    for i, (field, label, fmt) in enumerate(BARS):
        x0 = 4 + i * (GROUP_W + GROUP_GAP)
        top = max(float(values[s][field]) for s, _, _ in SOURCES)
        for k in range(1, 4):  # light guide lines
            gy = BASE_Y - BAR_MAX_H * k / 3
            parts.append(
                f'<line x1="{_f(x0)}" y1="{_f(gy)}" x2="{_f(x0 + GROUP_W)}" y2="{_f(gy)}" '
                f'stroke="{LINE}" stroke-width="1"/>'
            )
        for j, (source, fill, dashed) in enumerate(SOURCES):
            v = float(values[source][field])
            h = v / top * BAR_MAX_H if top > 0 else 0.0
            bx = x0 + 10 + j * (BAR_W + BAR_GAP)
            dash = ' stroke-dasharray="5 4"' if dashed else ""
            parts.append(
                f'<rect data-kpi="{field}" data-source="{source}" x="{_f(bx)}" '
                f'y="{BASE_Y - h:.2f}" width="{_f(BAR_W)}" height="{h:.2f}" rx="7" '
                f'fill="{fill}" stroke="{NAVY}" stroke-width="2.5"{dash}/>'
                f'<text x="{_f(bx + BAR_W / 2)}" y="{BASE_Y - h - 9:.2f}" font-size="17" '
                f'font-weight="700" fill="{NAVY}" text-anchor="middle">{fmt.format(v)}</text>'
            )
        parts.append(
            f'<line x1="{_f(x0)}" y1="{_f(BASE_Y)}" x2="{_f(x0 + GROUP_W)}" y2="{_f(BASE_Y)}" '
            f'stroke="{NAVY}" stroke-width="2.5"/>'
            f'<text x="{_f(x0)}" y="{_f(BASE_Y + 34)}" font-size="16" font-weight="700" '
            f'fill="{NAVY}">{_e(label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)
