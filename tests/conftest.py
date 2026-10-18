"""Shared test set-up: the Hypothesis profiles.

`make check` (and `make test`) run the default profile: every property test at its full number
of cases. `make test-quick` sets HYPOTHESIS_PROFILE=quick, a tenth of the cases, for a fast
inner loop while editing; it is never the gate before a push.
"""

from __future__ import annotations

import os

from hypothesis import settings

FULL = int(settings.get_profile("default").max_examples)
settings.register_profile("quick", max_examples=FULL // 10)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))
