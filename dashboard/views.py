"""P6.1 dashboard view logic: the API's JSON turned into what each panel shows. Pure functions,
no Streamlit, so they are unit-tested (tests/unit/test_dashboard_views.py).

Panels: the campus map (APs by channel and load, stations by association), the decision queue
(actions waiting for an operator), and twin vs live (each watched action's predicted KPIs next
to what the network then measured).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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


@dataclass(frozen=True)
class LoadBand:
    """A load class for the map legend: its name and what it means."""

    name: str
    meaning: str


BANDS = (
    LoadBand("calm", "under 60%"),
    LoadBand("busy", "60 to 80%"),
    LoadBand("congested", "80% or more"),
)


def load_band(util: float) -> LoadBand:
    """The band a utilisation (0 to 1) falls in."""
    if util >= CONGESTED:
        return BANDS[2]
    return BANDS[1] if util >= BUSY else BANDS[0]


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
            band = load_band(a["util"]).name
            label = f"{a['name']} · {channel} · {a['util']:.0%} · {n} clients"
        else:
            band, label = "down", f"{a['name']} · {channel} · down"
        aps.append(
            {
                "name": a["name"],
                "x": a["position"][0],
                "y": a["position"][1],
                "channel": channel,
                "load": round(a["util"], 3),
                "band": band,
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


def decision_queue(actions: list[Row]) -> list[Row]:
    """Actions an operator has to act on: approve (verified, needs approval) or apply (approved)."""
    queue = []
    for r in actions:
        needs = r["verdict"]["needs_approval"]
        if r["status"] == "verified" and needs:
            step = "approve"
        elif r["status"] == "approved":
            step = "apply"
        else:
            continue
        queue.append(
            {
                "action_id": r["action_id"],
                "next_step": step,
                "what": describe(r["action"]),
                "why": r["action"].get("reason", ""),
                "impact": r["verdict"]["impact"],
                "twin": _twin_says(r["verdict"]),
                "source": r["action"].get("source", ""),
            }
        )
    return queue


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


def verdict_word(verdict: Row) -> str:
    """The twin's verdict in a word, or the tool layer's refusal (invalid arguments)."""
    if "error" in verdict:
        return f"error: {verdict['error']}"
    return "accepted" if verdict["accepted"] else "rejected"


def _twin_says(verdict: Row) -> str:
    before, after = verdict.get("baseline") or {}, verdict.get("predicted") or {}
    head = verdict_word(verdict)
    if not before or not after:
        return head
    return (
        f"{head} · loss {before['loss_pct']:.1f}% → {after['loss_pct']:.1f}%"
        f" · latency {before['latency_ms']:.1f} → {after['latency_ms']:.1f} ms"
    )


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
                        "what": describe(r["action"]),
                        "outcome": r["status"],
                        "kpi": label,
                        "source": source,
                        "value": values[field],
                    }
                )
    return rows
