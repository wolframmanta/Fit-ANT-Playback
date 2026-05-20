from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from .models import PowerCadenceRecord

try:
    import fitdecode  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised on systems without fitdecode
    fitdecode = None  # type: ignore[assignment]


MissingValueMode = Literal["hold", "zero"]


def fitdecode_available() -> bool:
    return fitdecode is not None


class FitFileParser:
    """Parses FIT files to extract power and cadence records."""

    def __init__(self, missing_value_mode: MissingValueMode = "hold") -> None:
        if fitdecode is None:
            raise ImportError("fitdecode library not installed. Run: pip install fitdecode")
        if missing_value_mode not in ("hold", "zero"):
            raise ValueError("missing_value_mode must be 'hold' or 'zero'")
        self.missing_value_mode = missing_value_mode

    def parse(self, filepath: str | Path) -> list[PowerCadenceRecord]:
        records: list[PowerCadenceRecord] = []
        start_timestamp: float | None = None
        last_power: int | None = None
        last_cadence: int | None = None

        with fitdecode.FitReader(str(filepath)) as fit:  # type: ignore[union-attr]
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):  # type: ignore[union-attr]
                    continue
                if frame.name != "record":
                    continue

                fields = {field.name: field.value for field in frame.fields}
                timestamp_value = fields.get("timestamp")
                if timestamp_value is None:
                    continue

                timestamp = _timestamp_to_seconds(timestamp_value)
                if start_timestamp is None:
                    start_timestamp = timestamp
                relative_time = max(0.0, timestamp - start_timestamp)

                power_value = fields.get("power")
                cadence_value = fields.get("cadence")
                if power_value is None and cadence_value is None:
                    continue

                if power_value is None:
                    power = (
                        last_power
                        if self.missing_value_mode == "hold" and last_power is not None
                        else 0
                    )
                else:
                    power = _safe_int(power_value)
                    last_power = power

                if cadence_value is None:
                    cadence = (
                        last_cadence
                        if self.missing_value_mode == "hold" and last_cadence is not None
                        else 0
                    )
                else:
                    cadence = _safe_int(cadence_value)
                    last_cadence = cadence

                records.append(
                    PowerCadenceRecord(
                        timestamp=relative_time,
                        power=max(0, power),
                        cadence=max(0, cadence),
                    )
                )

        return records


def _timestamp_to_seconds(value: Any) -> float:
    if hasattr(value, "timestamp"):
        return float(value.timestamp())
    return float(value)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
