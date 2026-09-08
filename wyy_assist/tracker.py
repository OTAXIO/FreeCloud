from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Transition:
    previous: str | None
    current: str
    success_count: int
    ad_count: int
    changed: bool


class StableStateTracker:
    """Debounces visual states and counts ad/success state transitions."""

    def __init__(self, consecutive_hits: int = 2) -> None:
        if consecutive_hits < 1:
            raise ValueError("consecutive_hits must be >= 1")
        self.consecutive_hits = consecutive_hits
        self.current: str | None = None
        self._candidate: str | None = None
        self._candidate_hits = 0
        self.success_count = 0
        self.ad_count = 0

    def observe(self, state: str | None) -> Transition | None:
        if state is None:
            self._candidate = None
            self._candidate_hits = 0
            return None
        if state != self._candidate:
            self._candidate = state
            self._candidate_hits = 1
        else:
            self._candidate_hits += 1
        if self._candidate_hits < self.consecutive_hits:
            return None
        if state == self.current:
            return Transition(self.current, state, self.success_count, self.ad_count, False)
        previous = self.current
        self.current = state
        if state == "success":
            self.success_count += 1
        elif state in {"ad", "ad_interaction"}:
            self.ad_count += 1
        return Transition(previous, state, self.success_count, self.ad_count, True)
