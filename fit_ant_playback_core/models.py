from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PowerCadenceRecord:
    """Power and cadence sample at a FIT-file-relative timestamp."""

    timestamp: float
    power: int
    cadence: int
