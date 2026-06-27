import statistics
import unittest

from fit_ant_playback_core.ride_simulator import (
    RideSimulationConfig,
    RideSimulationError,
    generate_ride,
)


class RideSimulatorTests(unittest.TestCase):
    def test_generates_records_near_requested_targets(self):
        result = generate_ride(
            RideSimulationConfig(
                course_type="Rolling Course",
                duration_minutes=10,
                average_power=220,
                normalized_power=250,
                weight_kg=75,
                preferred_cadence=88,
                variability=0.8,
            ),
            seed=123,
        )

        self.assertEqual(result.records[0].timestamp, 0.0)
        self.assertEqual(result.records[-1].timestamp, 600.0)
        self.assertEqual(len(result.records), 601)
        self.assertAlmostEqual(result.average_power, 220, delta=2)
        self.assertAlmostEqual(result.normalized_power, 250, delta=4)
        self.assertGreater(result.variability_index, 1.0)
        self.assertTrue(all(record.power >= 0 for record in result.records))
        self.assertTrue(all(45 <= record.cadence <= 125 for record in result.records))

    def test_generation_is_repeatable_with_seed(self):
        config = RideSimulationConfig(
            course_type="Hilly Course",
            duration_minutes=5,
            average_power=200,
            normalized_power=230,
            weight_kg=70,
            preferred_cadence=82,
            variability=0.7,
        )

        first = generate_ride(config, seed=42)
        second = generate_ride(config, seed=42)

        self.assertEqual(first.records, second.records)

    def test_race_course_has_bigger_surges_than_steady_tt(self):
        common = dict(
            duration_minutes=8,
            average_power=210,
            normalized_power=245,
            weight_kg=75,
            preferred_cadence=90,
            variability=0.9,
        )
        steady = generate_ride(
            RideSimulationConfig(course_type="Steady TT", **common),
            seed=7,
        )
        race = generate_ride(
            RideSimulationConfig(course_type="Crit/Race Surges", **common),
            seed=7,
        )

        self.assertGreater(
            max(record.power for record in race.records),
            max(record.power for record in steady.records),
        )

    def test_mountain_climb_peak_spacing_is_not_clockwork(self):
        result = generate_ride(
            RideSimulationConfig(
                course_type="Mountain Climb",
                duration_minutes=45,
                average_power=220,
                normalized_power=245,
                weight_kg=75,
                preferred_cadence=88,
                variability=1.1,
            ),
            seed=123,
        )
        powers = [record.power for record in result.records]
        smoothed = _rolling_average(powers, window=30)
        peaks = _prominent_peaks(
            smoothed,
            min_gap=60,
            threshold=result.average_power * 1.04,
        )
        intervals = [later - earlier for earlier, later in zip(peaks, peaks[1:])]

        self.assertGreaterEqual(len(intervals), 6)
        self.assertGreater(statistics.pstdev(intervals), 45)
        self.assertGreaterEqual(min(powers), 105)

    def test_rejects_invalid_config(self):
        with self.assertRaises(RideSimulationError):
            generate_ride(
                RideSimulationConfig(
                    course_type="Rolling Course",
                    duration_minutes=0,
                    average_power=220,
                    normalized_power=250,
                    weight_kg=75,
                    preferred_cadence=88,
                    variability=0.8,
                )
            )


def _rolling_average(values: list[int], *, window: int) -> list[float]:
    averaged: list[float] = []
    half_window = window // 2
    for index in range(len(values)):
        start = max(0, index - half_window)
        end = min(len(values), index + half_window + 1)
        averaged.append(sum(values[start:end]) / (end - start))
    return averaged


def _prominent_peaks(
    values: list[float],
    *,
    min_gap: int,
    threshold: float,
) -> list[int]:
    peaks: list[int] = []
    for index in range(min_gap, len(values) - min_gap):
        if values[index] < threshold:
            continue
        neighborhood = values[index - min_gap : index + min_gap + 1]
        if values[index] == max(neighborhood) and (not peaks or index - peaks[-1] >= min_gap):
            peaks.append(index)
    return peaks


if __name__ == "__main__":
    unittest.main()
