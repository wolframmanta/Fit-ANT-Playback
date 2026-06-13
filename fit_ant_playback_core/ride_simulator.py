from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Literal

from .models import PowerCadenceRecord

CourseType = Literal[
    "Steady TT",
    "Endurance Ride",
    "Rolling Course",
    "Hilly Course",
    "Mountain Climb",
    "Crit/Race Surges",
    "VO2 Intervals",
]

COURSE_TYPES: tuple[CourseType, ...] = (
    "Steady TT",
    "Endurance Ride",
    "Rolling Course",
    "Hilly Course",
    "Mountain Climb",
    "Crit/Race Surges",
    "VO2 Intervals",
)

VARIABILITY_LEVELS: dict[str, float] = {
    "Low": 0.35,
    "Moderate": 0.60,
    "High": 0.85,
    "Very High": 1.10,
}


@dataclass(frozen=True)
class RideSimulationConfig:
    course_type: CourseType
    duration_minutes: float
    average_power: int
    normalized_power: int
    weight_kg: float
    preferred_cadence: int
    variability: float


@dataclass(frozen=True)
class RideSimulationResult:
    records: list[PowerCadenceRecord]
    average_power: float
    normalized_power: float
    average_cadence: float
    variability_index: float
    watts_per_kg: float


class RideSimulationError(ValueError):
    """Raised when simulator inputs cannot produce a ride."""


def generate_ride(
    config: RideSimulationConfig,
    *,
    seed: int | None = None,
) -> RideSimulationResult:
    _validate_config(config)
    rng = random.Random(seed)
    duration_seconds = max(1, int(round(config.duration_minutes * 60)))
    target_average = float(config.average_power)
    target_normalized = max(target_average, float(config.normalized_power))
    target_normalized = min(target_normalized, target_average * 2.2)

    raw_factors = _course_factors(config.course_type, duration_seconds, config.variability, rng)
    power_values = _scale_to_targets(raw_factors, target_average, target_normalized)
    cadence_values = _cadence_values(
        power_values=power_values,
        average_power=target_average,
        preferred_cadence=config.preferred_cadence,
        course_type=config.course_type,
        rng=rng,
    )

    records = [
        PowerCadenceRecord(timestamp=float(index), power=power, cadence=cadence)
        for index, (power, cadence) in enumerate(zip(power_values, cadence_values))
    ]
    average_power = _average([record.power for record in records])
    normalized_power = calculate_normalized_power([record.power for record in records])
    average_cadence = _average([record.cadence for record in records])

    return RideSimulationResult(
        records=records,
        average_power=average_power,
        normalized_power=normalized_power,
        average_cadence=average_cadence,
        variability_index=normalized_power / average_power if average_power > 0 else 0,
        watts_per_kg=average_power / config.weight_kg,
    )


def calculate_normalized_power(power_values: list[int]) -> float:
    if not power_values:
        return 0.0

    rolling: list[float] = []
    window_sum = 0.0
    window: list[int] = []
    for power in power_values:
        window.append(power)
        window_sum += power
        if len(window) > 30:
            window_sum -= window.pop(0)
        divisor = min(30, len(window))
        rolling.append(window_sum / divisor)

    fourth_power_average = sum(value**4 for value in rolling) / len(rolling)
    return fourth_power_average ** 0.25


def _validate_config(config: RideSimulationConfig) -> None:
    if config.course_type not in COURSE_TYPES:
        raise RideSimulationError(f"Unsupported course type: {config.course_type}")
    if config.duration_minutes <= 0:
        raise RideSimulationError("duration_minutes must be greater than zero")
    if config.average_power <= 0:
        raise RideSimulationError("average_power must be greater than zero")
    if config.normalized_power <= 0:
        raise RideSimulationError("normalized_power must be greater than zero")
    if config.weight_kg <= 0:
        raise RideSimulationError("weight_kg must be greater than zero")
    if config.preferred_cadence < 40 or config.preferred_cadence > 130:
        raise RideSimulationError("preferred_cadence must be between 40 and 130")
    if config.variability <= 0:
        raise RideSimulationError("variability must be greater than zero")


def _course_factors(
    course_type: CourseType,
    duration_seconds: int,
    variability: float,
    rng: random.Random,
) -> list[float]:
    if course_type == "Crit/Race Surges":
        return _race_factors(duration_seconds, variability, rng)
    if course_type == "VO2 Intervals":
        return _vo2_factors(duration_seconds, variability, rng)

    factors: list[float] = []
    phase_a = rng.uniform(0, math.tau)
    phase_b = rng.uniform(0, math.tau)
    phase_c = rng.uniform(0, math.tau)

    for second in range(duration_seconds + 1):
        t = float(second)
        if course_type == "Steady TT":
            factor = (
                1.0
                + variability * 0.025 * math.sin(t / 75 + phase_a)
                + variability * 0.015 * math.sin(t / 17 + phase_b)
            )
        elif course_type == "Endurance Ride":
            factor = (
                1.0
                + variability * 0.045 * math.sin(t / 180 + phase_a)
                + variability * 0.030 * math.sin(t / 45 + phase_b)
            )
            if second % 420 in range(8):
                factor += variability * 0.18
        elif course_type == "Rolling Course":
            factor = (
                1.0
                + variability * 0.16 * math.sin(t / 95 + phase_a)
                + variability * 0.08 * math.sin(t / 31 + phase_b)
                + variability * 0.035 * math.sin(t / 9 + phase_c)
            )
        elif course_type == "Hilly Course":
            factor = (
                1.0
                + variability * 0.28 * math.sin(t / 210 + phase_a)
                + variability * 0.11 * math.sin(t / 53 + phase_b)
            )
            if math.sin(t / 210 + phase_a) > 0.70:
                factor += variability * 0.16
        elif course_type == "Mountain Climb":
            progress = second / max(1, duration_seconds)
            factor = (
                0.92
                + 0.18 * progress
                + variability * 0.10 * math.sin(t / 160 + phase_a)
                + variability * 0.045 * math.sin(t / 29 + phase_b)
            )
        else:
            factor = 1.0

        factor += rng.uniform(-0.018, 0.018) * variability
        factors.append(max(0.35, factor))

    return _normalize_factors(factors)


def _race_factors(duration_seconds: int, variability: float, rng: random.Random) -> list[float]:
    factors = [0.88 + rng.uniform(-0.035, 0.035) * variability for _ in range(duration_seconds + 1)]

    cursor = 0
    while cursor <= duration_seconds:
        gap = rng.randint(25, 80)
        cursor += gap
        if cursor > duration_seconds:
            break
        surge_duration = rng.randint(8, 24)
        surge_factor = 1.45 + variability * rng.uniform(0.25, 0.70)
        for index in range(cursor, min(duration_seconds + 1, cursor + surge_duration)):
            factors[index] = surge_factor + rng.uniform(-0.08, 0.08)

        recovery_start = cursor + surge_duration
        recovery_duration = rng.randint(12, 35)
        for index in range(
            recovery_start,
            min(duration_seconds + 1, recovery_start + recovery_duration),
        ):
            factors[index] = 0.58 + variability * rng.uniform(0.02, 0.12)
        cursor = recovery_start + recovery_duration

    if duration_seconds > 45:
        for index in range(max(0, duration_seconds - 20), duration_seconds + 1):
            factors[index] = max(factors[index], 1.55 + variability * 0.35)

    return _normalize_factors([max(0.32, factor) for factor in factors])


def _vo2_factors(duration_seconds: int, variability: float, rng: random.Random) -> list[float]:
    factors: list[float] = []
    warmup_seconds = min(duration_seconds // 8, 300)
    interval_seconds = 180
    recovery_seconds = 180

    for second in range(duration_seconds + 1):
        if second < warmup_seconds:
            progress = second / max(1, warmup_seconds)
            factor = 0.62 + 0.28 * progress
        else:
            phase = (second - warmup_seconds) % (interval_seconds + recovery_seconds)
            if phase < interval_seconds:
                factor = 1.22 + variability * 0.13 + 0.03 * math.sin(phase / 18)
            else:
                factor = 0.58 + variability * 0.05 + 0.02 * math.sin(phase / 24)
        factor += rng.uniform(-0.015, 0.015) * variability
        factors.append(max(0.35, factor))

    return _normalize_factors(factors)


def _scale_to_targets(
    factors: list[float],
    target_average: float,
    target_normalized: float,
) -> list[int]:
    low = 0.0
    high = 6.0
    best = _powers_for_contrast(factors, target_average, low)
    best_delta = abs(calculate_normalized_power(best) - target_normalized)

    for _ in range(32):
        mid = (low + high) / 2
        candidate = _powers_for_contrast(factors, target_average, mid)
        candidate_np = calculate_normalized_power(candidate)
        delta = abs(candidate_np - target_normalized)
        if delta < best_delta:
            best = candidate
            best_delta = delta
        if candidate_np < target_normalized:
            low = mid
        else:
            high = mid

    return best


def _powers_for_contrast(
    factors: list[float],
    target_average: float,
    contrast: float,
) -> list[int]:
    adjusted = [max(0.18, 1.0 + contrast * (factor - 1.0)) for factor in factors]
    adjusted_average = _average(adjusted)
    scale = target_average / adjusted_average if adjusted_average > 0 else 1.0
    return [max(0, int(round(value * scale))) for value in adjusted]


def _cadence_values(
    *,
    power_values: list[int],
    average_power: float,
    preferred_cadence: int,
    course_type: CourseType,
    rng: random.Random,
) -> list[int]:
    values: list[int] = []
    for index, power in enumerate(power_values):
        relative = power / average_power if average_power > 0 else 1.0
        if course_type == "Mountain Climb":
            cadence = preferred_cadence - 7 + (relative - 1.0) * 8
        elif course_type in {"Crit/Race Surges", "VO2 Intervals"}:
            cadence = preferred_cadence + (relative - 1.0) * 13
        elif course_type == "Steady TT":
            cadence = preferred_cadence + (relative - 1.0) * 4
        else:
            cadence = preferred_cadence + (relative - 1.0) * 8

        cadence += 1.8 * math.sin(index / 22) + rng.uniform(-1.5, 1.5)
        values.append(max(45, min(125, int(round(cadence)))))

    return values


def _normalize_factors(values: list[float]) -> list[float]:
    average = _average(values)
    if average <= 0:
        return [1.0 for _ in values]
    return [value / average for value in values]


def _average(values: list[float] | list[int]) -> float:
    return sum(values) / len(values) if values else 0.0
