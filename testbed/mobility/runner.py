"""Scheduled-crowd runner (P1.4): moves walking stations in Mininet-WiFi and re-associates them.

Runs on the testbed VM (Python 3.8). Each tick it sets every walking station's position (which
moves it in wmediumd's radio model, so its signal follows); when a walk ends the station joins
the nearest AP (decision P1.4-A; stations never roam on their own, P1.4 probe). Steering runs in
its own thread so a ~4 s re-association does not stall the other walkers.
"""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass
from typing import Any, ContextManager, Sequence

from mininet.log import info

from testbed.layout import CampusLayout
from testbed.mobility.crowd import TICK_S, Walk, nearest_ap, position_at
from testbed.wifi_utils import steer


@dataclass(frozen=True)
class Arrival:
    """Outcome of one walk: the AP the station joined and whether it associated."""

    sta: str
    ap: str
    associated: bool
    t_s: float  # scenario time the walk ended


class CrowdRunner:
    """Plays a list of walks against a started campus (testbed/topologies/campus_v1.py).

    `lock` is the AP agent's lock when the agent is serving (node shells are shared).
    """

    def __init__(
        self,
        walks: Sequence[Walk],
        layout: CampusLayout,
        campus: Any,
        lock: ContextManager[Any] | None = None,
    ) -> None:
        self._walks = list(walks)
        self._layout = layout
        self._stations = {sta.name: sta for sta, _ in campus.stations}
        self._aps = dict(campus.aps)
        self._lock = lock if lock is not None else contextlib.nullcontext()
        self.arrivals: list[Arrival] = []

    def run(self, stop: threading.Event | None = None) -> list[Arrival]:
        """Play every walk from scenario time 0 (now); return once all walkers re-associated."""
        stop = stop or threading.Event()
        t0 = time.monotonic()
        pending = sorted(self._walks, key=lambda w: w.start_s)
        steering: list[threading.Thread] = []
        while pending and not stop.is_set():
            t = time.monotonic() - t0
            for walk in [w for w in pending if t >= w.start_s]:
                self._move(walk, position_at(walk, t))
                if t >= walk.end_s:
                    pending.remove(walk)
                    thread = threading.Thread(target=self._arrive, args=(walk,), daemon=True)
                    thread.start()
                    steering.append(thread)
            stop.wait(TICK_S)
        for thread in steering:
            thread.join()
        return self.arrivals

    def _move(self, walk: Walk, position: tuple[float, float]) -> None:
        with self._lock:
            self._stations[walk.sta].setPosition(f"{position[0]:.1f},{position[1]:.1f},0")

    def _arrive(self, walk: Walk) -> None:
        ap_name = nearest_ap(self._layout, walk.dst)
        ok = steer(self._stations[walk.sta], self._aps[ap_name], lock=self._lock)
        self.arrivals.append(Arrival(walk.sta, ap_name, ok, round(walk.end_s, 1)))
        info(f"CROWD_ARRIVED {walk.sta} -> {ap_name} associated={ok}\n")
