from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

from .models import PowerCadenceRecord

WORKOUT_FILE_EXTENSIONS = {".zwo", ".erg", ".mrc", ".xml", ".xert"}


class WorkoutParseError(ValueError):
    """Raised when a workout file cannot be parsed into power targets."""


@dataclass(frozen=True)
class WorkoutParseResult:
    records: list[PowerCadenceRecord]
    format_name: str
    ftp: int


@dataclass(frozen=True)
class _Segment:
    duration: float
    start_power: int
    end_power: int
    start_cadence: int
    end_cadence: int


def is_workout_file(filepath: str | Path) -> bool:
    return Path(filepath).suffix.lower() in WORKOUT_FILE_EXTENSIONS


class WorkoutFileParser:
    """Parses structured workout files into timestamped power/cadence targets."""

    def __init__(self, *, ftp: int = 250, default_cadence: int = 85) -> None:
        if ftp <= 0:
            raise ValueError("ftp must be greater than zero")
        if default_cadence < 0:
            raise ValueError("default_cadence must be zero or greater")
        self.ftp = int(ftp)
        self.default_cadence = int(default_cadence)

    def parse(self, filepath: str | Path) -> WorkoutParseResult:
        path = Path(filepath)
        suffix = path.suffix.lower()
        if suffix in {".zwo", ".xml", ".xert"}:
            try:
                return self._parse_xml_workout(path)
            except ET.ParseError as exc:
                raise WorkoutParseError(f"Workout XML is malformed: {exc}") from exc
        if suffix in {".erg", ".mrc"}:
            return self._parse_course_data(path, suffix=suffix)
        raise WorkoutParseError(f"Unsupported workout file extension: {suffix or '(none)'}")

    def _parse_xml_workout(self, path: Path) -> WorkoutParseResult:
        root = ET.parse(path).getroot()
        found_workout = _find_first(root, "workout")
        workout = found_workout if found_workout is not None else root
        segments: list[_Segment] = []
        previous_power = _power_from_target(0.60, self.ftp)

        for element in list(workout):
            tag = _local_name(element.tag).lower()
            if tag in {"textevent", "texteventxml", "name", "description", "tags", "sporttype"}:
                continue

            if tag == "intervalst":
                intervals = self._segments_from_intervals(element, previous_power)
                if intervals:
                    segments.extend(intervals)
                    previous_power = intervals[-1].end_power
                continue

            segment = self._segment_from_xml_step(element, previous_power)
            if segment is None:
                continue
            segments.append(segment)
            previous_power = segment.end_power

        if not segments:
            raise WorkoutParseError("No supported workout steps found")

        return WorkoutParseResult(
            records=_segments_to_records(segments),
            format_name="Zwift/XML workout",
            ftp=self.ftp,
        )

    def _segment_from_xml_step(
        self,
        element: ET.Element,
        previous_power: int,
    ) -> _Segment | None:
        duration = _get_float_attr(element, "Duration", "duration")
        if duration is None or duration <= 0:
            return None

        steady_watts = _get_float_attr(element, "Watts", "TargetWatts")
        steady_power = _get_float_attr(element, "Power", "power", "TargetPower")
        power_low = _get_float_attr(element, "PowerLow", "powerLow", "power_low", "StartPower")
        power_high = _get_float_attr(element, "PowerHigh", "powerHigh", "power_high", "EndPower")

        if steady_watts is not None:
            start_power = end_power = int(round(steady_watts))
        elif steady_power is not None:
            start_power = end_power = _power_from_target(steady_power, self.ftp)
        elif power_low is not None and power_high is not None:
            start_power = _power_from_target(power_low, self.ftp)
            end_power = _power_from_target(power_high, self.ftp)
        elif power_low is not None:
            start_power = end_power = _power_from_target(power_low, self.ftp)
        elif power_high is not None:
            start_power = end_power = _power_from_target(power_high, self.ftp)
        else:
            start_power = end_power = previous_power

        cadence = _get_int_attr(element, "Cadence", "cadence", "TargetCadence")
        cadence_low = _get_int_attr(element, "CadenceLow", "cadenceLow", "StartCadence")
        cadence_high = _get_int_attr(element, "CadenceHigh", "cadenceHigh", "EndCadence")
        if cadence is not None:
            start_cadence = end_cadence = cadence
        else:
            start_cadence = cadence_low if cadence_low is not None else self.default_cadence
            end_cadence = cadence_high if cadence_high is not None else start_cadence

        return _Segment(
            duration=duration,
            start_power=start_power,
            end_power=end_power,
            start_cadence=start_cadence,
            end_cadence=end_cadence,
        )

    def _segments_from_intervals(
        self,
        element: ET.Element,
        previous_power: int,
    ) -> list[_Segment]:
        repeat = max(1, _get_int_attr(element, "Repeat", "repeat", "Repeats") or 1)
        on_duration = _get_float_attr(element, "OnDuration", "DurationOn", "onDuration")
        off_duration = _get_float_attr(element, "OffDuration", "DurationOff", "offDuration")
        on_power_raw = _get_float_attr(element, "OnPower", "PowerOn", "onPower")
        off_power_raw = _get_float_attr(element, "OffPower", "PowerOff", "offPower")

        if on_duration is None or on_duration <= 0 or off_duration is None or off_duration < 0:
            return []

        on_power = _power_from_target(on_power_raw, self.ftp) if on_power_raw is not None else previous_power
        off_power = (
            _power_from_target(off_power_raw, self.ftp)
            if off_power_raw is not None
            else _power_from_target(0.50, self.ftp)
        )
        on_cadence = (
            _get_int_attr(element, "OnCadence", "CadenceOn", "onCadence", "Cadence")
            or self.default_cadence
        )
        off_cadence = (
            _get_int_attr(element, "OffCadence", "CadenceOff", "offCadence", "CadenceResting")
            or self.default_cadence
        )

        segments: list[_Segment] = []
        for _ in range(repeat):
            segments.append(_Segment(on_duration, on_power, on_power, on_cadence, on_cadence))
            if off_duration > 0:
                segments.append(_Segment(off_duration, off_power, off_power, off_cadence, off_cadence))
        return segments

    def _parse_course_data(self, path: Path, *, suffix: str) -> WorkoutParseResult:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        header_lines: list[str] = []
        data_points: list[tuple[float, float]] = []
        in_header = False
        in_data = False

        for raw_line in lines:
            line = raw_line.strip()
            upper = line.upper()
            if not line or line.startswith(("#", ";")):
                continue
            if upper == "[COURSE HEADER]":
                in_header = True
                in_data = False
                continue
            if upper == "[COURSE DATA]":
                in_header = False
                in_data = True
                continue
            if upper in {"[END COURSE HEADER]", "[END COURSE DATA]"}:
                in_header = False
                in_data = False
                continue

            if in_header:
                header_lines.append(upper)
                continue
            if not in_data:
                continue

            parts = line.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                data_points.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue

        if len(data_points) < 2:
            raise WorkoutParseError("Course-data workout must include at least two data points")

        header_text = "\n".join(header_lines)
        uses_seconds = "SECONDS" in header_text
        uses_watts = "WATTS" in header_text or suffix == ".erg"
        has_percent_targets = "PERCENT" in header_text or suffix == ".mrc"
        if uses_watts and has_percent_targets:
            uses_watts = suffix == ".erg"

        records: list[PowerCadenceRecord] = []
        for raw_time, raw_target in data_points:
            timestamp = raw_time if uses_seconds else raw_time * 60
            power = int(round(raw_target)) if uses_watts else _power_from_course_percent(raw_target, self.ftp)
            records.append(
                PowerCadenceRecord(
                    timestamp=max(0.0, timestamp),
                    power=max(0, power),
                    cadence=self.default_cadence,
                )
            )

        records.sort(key=lambda record: record.timestamp)
        return WorkoutParseResult(
            records=records,
            format_name="ERG workout" if uses_watts else "MRC workout",
            ftp=self.ftp,
        )


def _segments_to_records(segments: list[_Segment]) -> list[PowerCadenceRecord]:
    records: list[PowerCadenceRecord] = []
    cursor = 0.0
    for segment in segments:
        steps = max(1, int(round(segment.duration)))
        for step in range(steps + 1):
            fraction = step / steps
            timestamp = cursor + segment.duration * fraction
            power = round(segment.start_power + (segment.end_power - segment.start_power) * fraction)
            cadence = round(
                segment.start_cadence
                + (segment.end_cadence - segment.start_cadence) * fraction
            )
            _append_or_replace(
                records,
                PowerCadenceRecord(
                    timestamp=timestamp,
                    power=max(0, int(power)),
                    cadence=max(0, int(cadence)),
                ),
            )
        cursor += segment.duration
    return records


def _append_or_replace(records: list[PowerCadenceRecord], record: PowerCadenceRecord) -> None:
    if records and abs(records[-1].timestamp - record.timestamp) < 0.000001:
        records[-1] = record
    else:
        records.append(record)


def _find_first(root: ET.Element, local_name: str) -> ET.Element | None:
    target = local_name.lower()
    for element in root.iter():
        if _local_name(element.tag).lower() == target:
            return element
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _get_attr(element: ET.Element, *names: str) -> str | None:
    lookup = {key.lower(): value for key, value in element.attrib.items()}
    for name in names:
        value = lookup.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _get_float_attr(element: ET.Element, *names: str) -> float | None:
    value = _get_attr(element, *names)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _get_int_attr(element: ET.Element, *names: str) -> int | None:
    value = _get_float_attr(element, *names)
    return None if value is None else int(round(value))


def _power_from_target(value: float | int | None, ftp: int) -> int:
    if value is None:
        return 0
    target = float(value)
    if target <= 5:
        return int(round(target * ftp))
    if target <= 200:
        return int(round((target / 100) * ftp))
    return int(round(target))


def _power_from_course_percent(value: float, ftp: int) -> int:
    if value <= 2.5:
        return int(round(value * ftp))
    return int(round((value / 100) * ftp))
