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


@dataclass(frozen=True)
class _NaturalCourseShape:
    start_factor: float
    finish_factor: float
    long_amplitude: float
    medium_amplitude: float
    short_amplitude: float
    effort_amplitude: float
    jitter_amplitude: float
    minimum_factor: float
    long_segment_seconds: tuple[int, int]
    medium_segment_seconds: tuple[int, int]
    short_segment_seconds: tuple[int, int]
    event_gap_seconds: tuple[int, int]
    event_duration_seconds: tuple[int, int]
    event_amount: tuple[float, float]
    recovery_duration_seconds: tuple[int, int]
    recovery_amount: tuple[float, float]
    settle_event_chance: float


_NATURAL_COURSE_SHAPES: dict[str, _NaturalCourseShape] = {
    "Steady TT": _NaturalCourseShape(
        start_factor=0.98,
        finish_factor=1.01,
        long_amplitude=0.020,
        medium_amplitude=0.014,
        short_amplitude=0.008,
        effort_amplitude=0.010,
        jitter_amplitude=0.005,
        minimum_factor=0.72,
        long_segment_seconds=(260, 720),
        medium_segment_seconds=(70, 210),
        short_segment_seconds=(18, 55),
        event_gap_seconds=(360, 900),
        event_duration_seconds=(10, 28),
        event_amount=(0.015, 0.045),
        recovery_duration_seconds=(15, 45),
        recovery_amount=(0.010, 0.030),
        settle_event_chance=0.20,
    ),
    "Endurance Ride": _NaturalCourseShape(
        start_factor=0.95,
        finish_factor=0.98,
        long_amplitude=0.055,
        medium_amplitude=0.036,
        short_amplitude=0.018,
        effort_amplitude=0.018,
        jitter_amplitude=0.008,
        minimum_factor=0.55,
        long_segment_seconds=(360, 1200),
        medium_segment_seconds=(90, 320),
        short_segment_seconds=(20, 75),
        event_gap_seconds=(240, 780),
        event_duration_seconds=(8, 32),
        event_amount=(0.030, 0.090),
        recovery_duration_seconds=(20, 70),
        recovery_amount=(0.015, 0.055),
        settle_event_chance=0.35,
    ),
    "Rolling Course": _NaturalCourseShape(
        start_factor=0.96,
        finish_factor=1.00,
        long_amplitude=0.135,
        medium_amplitude=0.075,
        short_amplitude=0.030,
        effort_amplitude=0.026,
        jitter_amplitude=0.010,
        minimum_factor=0.42,
        long_segment_seconds=(220, 760),
        medium_segment_seconds=(55, 210),
        short_segment_seconds=(14, 55),
        event_gap_seconds=(120, 420),
        event_duration_seconds=(8, 36),
        event_amount=(0.035, 0.120),
        recovery_duration_seconds=(18, 80),
        recovery_amount=(0.020, 0.070),
        settle_event_chance=0.28,
    ),
    "Hilly Course": _NaturalCourseShape(
        start_factor=0.93,
        finish_factor=1.01,
        long_amplitude=0.205,
        medium_amplitude=0.115,
        short_amplitude=0.042,
        effort_amplitude=0.032,
        jitter_amplitude=0.012,
        minimum_factor=0.36,
        long_segment_seconds=(280, 980),
        medium_segment_seconds=(65, 260),
        short_segment_seconds=(16, 70),
        event_gap_seconds=(90, 360),
        event_duration_seconds=(10, 42),
        event_amount=(0.040, 0.145),
        recovery_duration_seconds=(20, 90),
        recovery_amount=(0.020, 0.085),
        settle_event_chance=0.22,
    ),
    "Mountain Climb": _NaturalCourseShape(
        start_factor=0.90,
        finish_factor=1.07,
        long_amplitude=0.185,
        medium_amplitude=0.135,
        short_amplitude=0.060,
        effort_amplitude=0.040,
        jitter_amplitude=0.013,
        minimum_factor=0.40,
        long_segment_seconds=(420, 1600),
        medium_segment_seconds=(85, 360),
        short_segment_seconds=(18, 80),
        event_gap_seconds=(75, 420),
        event_duration_seconds=(8, 50),
        event_amount=(0.035, 0.165),
        recovery_duration_seconds=(20, 95),
        recovery_amount=(0.020, 0.095),
        settle_event_chance=0.16,
    ),
}

_STANDING_SPIKE_RATE_PER_HOUR: dict[str, float] = {
    "Steady TT": 0.7,
    "Endurance Ride": 2.0,
    "Rolling Course": 2.7,
    "Hilly Course": 3.1,
    "Mountain Climb": 2.8,
}

_STANDING_SPIKE_AMOUNT: dict[str, tuple[float, float]] = {
    "Steady TT": (0.14, 0.26),
    "Endurance Ride": (0.22, 0.38),
    "Rolling Course": (0.28, 0.52),
    "Hilly Course": (0.30, 0.58),
    "Mountain Climb": (0.26, 0.48),
}


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

    raw_factors, standing_effort = _course_factors(config.course_type, duration_seconds, config.variability, rng)
    power_values = _scale_to_targets(
        raw_factors,
        target_average,
        target_normalized,
        minimum_power_fraction=_minimum_power_fraction(config.course_type),
    )
    cadence_values = _cadence_values(
        power_values=power_values,
        average_power=target_average,
        preferred_cadence=config.preferred_cadence,
        course_type=config.course_type,
        standing_effort=standing_effort,
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
) -> tuple[list[float], list[float]]:
    if course_type == "Crit/Race Surges":
        return _race_factors(duration_seconds, variability, rng), [0.0 for _ in range(duration_seconds + 1)]
    if course_type == "VO2 Intervals":
        return _vo2_factors(duration_seconds, variability, rng), [0.0 for _ in range(duration_seconds + 1)]
    return _natural_factors(course_type, duration_seconds, variability, rng)


def _natural_factors(
    course_type: CourseType,
    duration_seconds: int,
    variability: float,
    rng: random.Random,
) -> tuple[list[float], list[float]]:
    shape = _NATURAL_COURSE_SHAPES[course_type]
    terrain_long = _smooth_random_profile(duration_seconds, shape.long_segment_seconds, rng)
    terrain_medium = _smooth_random_profile(duration_seconds, shape.medium_segment_seconds, rng)
    terrain_short = _smooth_random_profile(duration_seconds, shape.short_segment_seconds, rng)
    rider_effort = _mean_reverting_noise(
        duration_seconds,
        scale=shape.effort_amplitude * variability,
        rng=rng,
    )

    factors: list[float] = []
    for second in range(duration_seconds + 1):
        progress = second / max(1, duration_seconds)
        course_trend = shape.start_factor + (shape.finish_factor - shape.start_factor) * _smoothstep(progress)
        terrain = (
            shape.long_amplitude * terrain_long[second]
            + shape.medium_amplitude * terrain_medium[second]
            + shape.short_amplitude * terrain_short[second]
        )
        factor = course_trend + variability * terrain + rider_effort[second]
        factor += rng.gauss(0.0, shape.jitter_amplitude * variability)
        factors.append(max(shape.minimum_factor, factor))

    _apply_irregular_events(factors, shape, variability, rng)
    standing_effort = _apply_standing_spikes(factors, course_type, variability, rng)
    return _normalize_factors(factors), standing_effort


def _smooth_random_profile(
    duration_seconds: int,
    segment_seconds: tuple[int, int],
    rng: random.Random,
) -> list[float]:
    values = [0.0 for _ in range(duration_seconds + 1)]
    current = rng.uniform(-1.0, 1.0)
    cursor = 0

    while cursor <= duration_seconds:
        segment_length = rng.randint(*segment_seconds)
        next_value = rng.uniform(-1.0, 1.0)
        end = min(duration_seconds, cursor + segment_length)
        span = max(1, end - cursor)
        for index in range(cursor, end + 1):
            progress = (index - cursor) / span
            values[index] = current + (next_value - current) * _smoothstep(progress)
        current = next_value
        cursor = end + 1

    return values


def _mean_reverting_noise(
    duration_seconds: int,
    *,
    scale: float,
    rng: random.Random,
) -> list[float]:
    values: list[float] = []
    state = rng.uniform(-scale, scale)
    for _ in range(duration_seconds + 1):
        state = state * 0.994 + rng.gauss(0.0, scale * 0.075)
        state = max(-scale * 2.2, min(scale * 2.2, state))
        values.append(state)
    return values


def _apply_irregular_events(
    factors: list[float],
    shape: _NaturalCourseShape,
    variability: float,
    rng: random.Random,
) -> None:
    if not factors:
        return

    cursor = rng.randint(*shape.event_gap_seconds)
    while cursor < len(factors):
        event_duration = rng.randint(*shape.event_duration_seconds)
        event_amount = rng.uniform(*shape.event_amount) * variability
        if rng.random() < shape.settle_event_chance:
            event_amount *= -rng.uniform(0.45, 0.85)

        for offset in range(event_duration):
            index = cursor + offset
            if index >= len(factors):
                break
            progress = offset / max(1, event_duration - 1)
            factors[index] += event_amount * math.sin(math.pi * progress)

        recovery_start = cursor + event_duration
        recovery_duration = rng.randint(*shape.recovery_duration_seconds)
        recovery_amount = rng.uniform(*shape.recovery_amount) * variability
        if event_amount < 0:
            recovery_amount *= -0.45

        for offset in range(recovery_duration):
            index = recovery_start + offset
            if index >= len(factors):
                break
            progress = offset / max(1, recovery_duration - 1)
            factors[index] -= recovery_amount * math.sin(math.pi * progress)

        cursor = recovery_start + recovery_duration + rng.randint(*shape.event_gap_seconds)


def _apply_standing_spikes(
    factors: list[float],
    course_type: CourseType,
    variability: float,
    rng: random.Random,
) -> list[float]:
    standing_effort = [0.0 for _ in factors]
    if len(factors) < 300 or course_type not in _STANDING_SPIKE_RATE_PER_HOUR:
        return standing_effort

    duration_seconds = len(factors) - 1
    rate = _STANDING_SPIKE_RATE_PER_HOUR[course_type]
    expected_count = (duration_seconds / 3600) * rate * max(0.65, min(1.15, variability))
    spike_count = int(expected_count)
    if rng.random() < expected_count - spike_count:
        spike_count += 1
    if duration_seconds >= 1800 and course_type != "Steady TT":
        spike_count = max(1, spike_count)
    if duration_seconds >= 3600 and course_type in {"Endurance Ride", "Rolling Course", "Hilly Course", "Mountain Climb"}:
        spike_count = max(2, spike_count)
    if spike_count <= 0:
        return standing_effort

    min_amount, max_amount = _STANDING_SPIKE_AMOUNT[course_type]
    spacing = duration_seconds / (spike_count + 1)
    for spike_index in range(spike_count):
        center = int(round((spike_index + 1) * spacing + rng.uniform(-spacing * 0.18, spacing * 0.18)))
        duration = rng.randint(15, 22)
        start = max(20, center - duration // 2)
        amount = rng.uniform(min_amount, max_amount) * (0.80 + 0.25 * variability)

        for offset in range(duration):
            index = start + offset
            if index >= len(factors):
                break
            progress = offset / max(1, duration - 1)
            if progress < 0.22:
                shape = _smoothstep(progress / 0.22)
            elif progress > 0.78:
                shape = _smoothstep((1.0 - progress) / 0.22)
            else:
                shape = 1.0
            factors[index] += amount * shape
            standing_effort[index] = max(standing_effort[index], shape)

        recovery_start = start + duration
        recovery_duration = rng.randint(28, 70)
        recovery_amount = amount * rng.uniform(0.10, 0.20)
        for offset in range(recovery_duration):
            index = recovery_start + offset
            if index >= len(factors):
                break
            progress = offset / max(1, recovery_duration - 1)
            factors[index] -= recovery_amount * math.sin(math.pi * progress)

    return standing_effort


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
    *,
    minimum_power_fraction: float,
) -> list[int]:
    low = 0.0
    high = 6.0
    best = _powers_for_contrast(
        factors,
        target_average,
        low,
        minimum_power_fraction=minimum_power_fraction,
    )
    best_delta = abs(calculate_normalized_power(best) - target_normalized)

    for _ in range(32):
        mid = (low + high) / 2
        candidate = _powers_for_contrast(
            factors,
            target_average,
            mid,
            minimum_power_fraction=minimum_power_fraction,
        )
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


def _minimum_power_fraction(course_type: CourseType) -> float:
    if course_type == "Mountain Climb":
        return 0.50
    if course_type == "Steady TT":
        return 0.62
    if course_type == "Endurance Ride":
        return 0.36
    if course_type == "Rolling Course":
        return 0.28
    if course_type == "Hilly Course":
        return 0.32
    if course_type == "VO2 Intervals":
        return 0.24
    return 0.16


def _powers_for_contrast(
    factors: list[float],
    target_average: float,
    contrast: float,
    *,
    minimum_power_fraction: float,
) -> list[int]:
    adjusted = [
        max(minimum_power_fraction, 1.0 + contrast * (factor - 1.0))
        for factor in factors
    ]
    adjusted_average = _average(adjusted)
    scale = target_average / adjusted_average if adjusted_average > 0 else 1.0
    return [max(0, int(round(value * scale))) for value in adjusted]


def _cadence_values(
    *,
    power_values: list[int],
    average_power: float,
    preferred_cadence: int,
    course_type: CourseType,
    standing_effort: list[float],
    rng: random.Random,
) -> list[int]:
    values: list[int] = []
    cadence_drift = rng.uniform(-1.5, 1.5)
    gear_offset = rng.uniform(-0.8, 0.8)
    gear_target = gear_offset
    pedal_noise = rng.gauss(0.0, 0.25)
    next_shift = rng.randint(35, 150)
    total_records = max(1, len(power_values) - 1)
    cadence = float(preferred_cadence) + rng.uniform(-1.0, 1.0)
    reported_cadence: int | None = None

    if course_type in {"Crit/Race Surges", "VO2 Intervals"}:
        response = 0.20
        max_step = 3.0
        report_threshold = 0.65
        drift_noise = 0.045
        pedal_noise_amount = 0.13
        gear_response = 0.055
    elif course_type == "Mountain Climb":
        response = 0.07
        max_step = 0.8
        report_threshold = 1.20
        drift_noise = 0.025
        pedal_noise_amount = 0.08
        gear_response = 0.035
    elif course_type == "Steady TT":
        response = 0.035
        max_step = 0.35
        report_threshold = 1.75
        drift_noise = 0.012
        pedal_noise_amount = 0.035
        gear_response = 0.018
    elif course_type == "Endurance Ride":
        response = 0.055
        max_step = 0.5
        report_threshold = 1.45
        drift_noise = 0.018
        pedal_noise_amount = 0.05
        gear_response = 0.022
    else:
        response = 0.09
        max_step = 1.0
        report_threshold = 0.95
        drift_noise = 0.030
        pedal_noise_amount = 0.09
        gear_response = 0.040

    for index, power in enumerate(power_values):
        relative = power / average_power if average_power > 0 else 1.0
        if course_type == "Mountain Climb":
            target_cadence = preferred_cadence - 7 + (relative - 1.0) * 5
            target_cadence -= max(0.0, relative - 1.16) * 9
        elif course_type in {"Crit/Race Surges", "VO2 Intervals"}:
            target_cadence = preferred_cadence + (relative - 1.0) * 13
        elif course_type == "Steady TT":
            target_cadence = preferred_cadence + (relative - 1.0) * 2.5
        elif course_type == "Endurance Ride":
            target_cadence = preferred_cadence + (relative - 1.0) * 4.5
        else:
            target_cadence = preferred_cadence + (relative - 1.0) * 8

        standing = standing_effort[index] if index < len(standing_effort) else 0.0
        if standing > 0:
            standing_target = max(50.0, min(68.0, 58.0 - max(0.0, relative - 1.0) * 6.0))
            target_cadence = target_cadence * (1.0 - standing) + standing_target * standing

        if index >= next_shift:
            gear_target = gear_target * 0.5 + rng.choice((-1.0, 1.0)) * rng.uniform(0.7, 2.2)
            next_shift += rng.randint(40, 210)

        gear_offset += (gear_target - gear_offset) * gear_response
        cadence_drift = cadence_drift * 0.994 + rng.gauss(0.0, drift_noise)
        pedal_noise = pedal_noise * 0.86 + rng.gauss(0.0, pedal_noise_amount)
        fatigue_drop = (index / total_records) * (2.5 if course_type == "Mountain Climb" else 0.8)
        desired = target_cadence + cadence_drift + gear_offset - fatigue_drop + pedal_noise
        effective_response = max(response, 0.30 * standing)
        effective_max_step = max(max_step, 3.0 * standing)
        delta = (desired - cadence) * effective_response
        delta = max(-effective_max_step, min(effective_max_step, delta))
        cadence += delta
        candidate = max(45, min(125, int(round(cadence))))
        effective_report_threshold = min(report_threshold, 0.70) if standing > 0.05 else report_threshold
        if reported_cadence is None:
            reported_cadence = candidate
        elif cadence >= reported_cadence + effective_report_threshold:
            reported_cadence += 2 if standing > 0.75 else 1
        elif cadence <= reported_cadence - effective_report_threshold:
            reported_cadence -= 2 if standing > 0.75 else 1
        values.append(reported_cadence)

    return values


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _normalize_factors(values: list[float]) -> list[float]:
    average = _average(values)
    if average <= 0:
        return [1.0 for _ in values]
    return [value / average for value in values]


def _average(values: list[float] | list[int]) -> float:
    return sum(values) / len(values) if values else 0.0
