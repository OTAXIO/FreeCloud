from __future__ import annotations

import random


def jitter_wait_seconds(seconds: float) -> float:
    """Vary a configured wait by at most one second, in tenths of a second."""
    if seconds <= 0:
        return 0.0
    return round(max(0.0, seconds + random.randint(-10, 10) / 10), 1)
