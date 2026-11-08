"""The number checks every testbed validator shares (config YAML and AP agent JSON bodies).

Finite only: YAML (.nan, .inf) and json.loads (NaN, Infinity) both accept non-finite floats,
and those slip past a one-sided bound such as `value < 0` (every comparison with NaN is False).
"""

from __future__ import annotations

import math
from typing import Any


def is_number(value: Any) -> bool:
    """True for a finite int or float; never a bool (True is an int in Python)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def is_int(value: Any) -> bool:
    """True for an int; never a bool."""
    return isinstance(value, int) and not isinstance(value, bool)
