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


if __name__ == "__main__":
    unittest.main()
