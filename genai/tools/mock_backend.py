"""Mock backend for the tool layer (P5.2 until the live API, Oct 20): recorded VM responses.

Topology (in the live /topology shape) and AP data come from tests/fixtures/ap_agent; metrics
from the KPI probe and AP stats fixtures; there are no alerts. The twin is faked
deterministically: every action is accepted with a small predicted gain, and its impact class
and approval rule are the real ones (common/schemas.py impact_of). Like the real executor,
apply() re-checks the verdict.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from common.schemas import Action, KPIValues, Verdict, impact_of

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
# Made-up KPI values: the mock twin only needs to return a schema-valid verdict.
_BASELINE = KPIValues(throughput_mbps=20.0, latency_ms=30.0, loss_pct=1.0, jain=0.8)
_PREDICTED = KPIValues(throughput_mbps=20.4, latency_ms=29.0, loss_pct=0.9, jain=0.82)


class MockBackend:
    """Backend (genai/tools/backend.py) over the recorded fixtures."""

    def __init__(self, fixtures: Path = FIXTURES) -> None:
        self._fixtures = fixtures
        self._verdicts: dict[str, Verdict] = {}
        kpis = (fixtures / "traffic/kpi_records.jsonl").read_text().splitlines()
        rows = [json.loads(line) for line in kpis] + self._json("ap_agent/ap_agent_ap_stats.json")[
            "aps"
        ]
        # (time, record) once, so metrics() does no file I/O or date parsing per call
        self._series = [(datetime.fromisoformat(r["ts"]), r) for r in rows]

    def topology(self) -> dict[str, Any]:
        """The recorded network in the shape of the live GET /topology (the twin state)."""
        util = {
            a["ap"]: a["channel_util"] for a in self._json("ap_agent/ap_agent_ap_stats.json")["aps"]
        }
        aps = [
            {
                "name": a["ap"],
                "position": [a["x"], a["y"]],
                "channel": a["channel"],
                "up": True,
                "util": util.get(a["ap"], 0.0),
                "tx_power_dbm": a["tx_power_dbm"],
            }
            for a in self._json("ap_agent/ap_agent_aps.json")["aps"]
        ]
        stations = [
            {"name": s["sta"], "position": [s["x"], s["y"]], "ap": s["ap"], "zone": None}
            for s in self._json("ap_agent/ap_agent_stations.json")["stations"]
        ]
        latest = {r["flow_id"]: r for _, r in self._series if "flow_id" in r}
        flows = [
            {
                "flow_id": f,
                "sta": f.split("-")[0],
                "app_class": r["app_class"],
                "throughput_mbps": r["throughput_mbps"],
                "latency_ms": r["latency_ms"],
                "loss_pct": r["loss_pct"],
            }
            for f, r in sorted(latest.items())
        ]
        return {"aps": aps, "stations": stations, "flows": flows}

    def metrics(self, entity: str, metric: str, window_s: int) -> list[dict[str, Any]]:
        mine = [
            (t, r)
            for t, r in self._series
            if entity in (r.get("flow_id"), r.get("ap")) and metric in r
        ]
        if not mine:
            return []
        # recorded data: the window ends at the newest sample, not now (the live backend: now)
        since = max(t for t, _ in mine) - timedelta(seconds=window_s)
        return [{"ts": r["ts"], "value": r[metric]} for t, r in mine if t >= since]

    def alerts(self, since_s: int) -> list[dict[str, Any]]:
        return []

    def simulate(self, action: Action) -> Verdict:
        impact = impact_of(action)
        verdict = Verdict(
            action_id=action.action_id,
            accepted=True,
            predicted=_PREDICTED,
            baseline=_BASELINE,
            impact=impact,
            needs_approval=impact == "high",
            sim_mode="analytical",
            sim_time_ms=1.0,
        )
        self._verdicts[action.action_id] = verdict
        return verdict

    def apply(self, action_id: str) -> dict[str, Any]:
        verdict = self._verdicts.get(action_id)
        if verdict is None or not verdict.accepted:
            raise ValueError(f"backend: no accepted twin verdict for {action_id}")
        return {"action_id": action_id, "status": "applied"}

    def _json(self, path: str) -> Any:
        return json.loads((self._fixtures / path).read_text())
