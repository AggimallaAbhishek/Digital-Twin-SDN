"""P4.2 anomaly detector: Isolation Forest over whole-network window features.

Fitted on normal windows only (the train split's normal runs and pre-onset windows), so
anything unlike normal operation scores high. Score = -score_samples (higher = more anomalous);
the alert threshold is chosen elsewhere (on the val split, metrics.best_threshold). The alert's
entity is the AP whose features deviate most from normal (largest |z| against the training
windows), or "network" when a network-wide feature deviates most.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import IsolationForest

MIN_STD = 1e-6  # features that never vary in normal operation (e.g. an AP being silent)


@dataclass
class Detector:
    """A fitted Isolation Forest plus the normal feature statistics used to name the entity."""

    forest: IsolationForest
    names: list[str]
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(
        cls, normal: Sequence[Sequence[float]], names: Sequence[str], seed: int, n_estimators: int
    ) -> Detector:
        """Fit on windows of normal operation (seeded: RULEBOOK E-1)."""
        x = np.asarray(normal, dtype=float)
        forest = IsolationForest(n_estimators=n_estimators, random_state=seed).fit(x)
        return cls(forest, list(names), x.mean(axis=0), np.maximum(x.std(axis=0), MIN_STD))

    def score(self, windows: Sequence[Sequence[float]]) -> list[float]:
        """Anomaly score of each window (higher = more unusual)."""
        return [float(-s) for s in self.forest.score_samples(np.asarray(windows, dtype=float))]

    def entity(self, window: Sequence[float]) -> str:
        """The AP (e.g. "ap2") whose features deviate most, or "network"."""
        z = np.abs((np.asarray(window, dtype=float) - self.mean) / self.std)
        worst = self.names[int(np.argmax(z))].split(".", 1)[0]
        return "network" if worst == "net" else worst
