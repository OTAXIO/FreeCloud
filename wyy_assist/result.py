from dataclasses import dataclass


@dataclass(frozen=True)
class AutomationResult:
    reason: str
    transitions: int
