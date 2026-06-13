import tempfile
import unittest
from pathlib import Path

from fit_ant_playback_core.workout_parser import WorkoutFileParser, WorkoutParseError


class WorkoutParserTests(unittest.TestCase):
    def test_parses_zwift_workout_steps_and_intervals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.zwo"
            path.write_text(
                """
                <workout_file>
                  <workout>
                    <Warmup Duration="10" PowerLow="0.50" PowerHigh="0.70" Cadence="90"/>
                    <SteadyState Duration="20" Power="0.80" Cadence="88"/>
                    <IntervalsT Repeat="2" OnDuration="5" OffDuration="5"
                                OnPower="1.10" OffPower="0.55"
                                OnCadence="95" OffCadence="80"/>
                  </workout>
                </workout_file>
                """,
                encoding="utf-8",
            )

            result = WorkoutFileParser(ftp=300).parse(path)

        self.assertEqual(result.format_name, "Zwift/XML workout")
        self.assertEqual(result.records[0].timestamp, 0.0)
        self.assertEqual(result.records[0].power, 150)
        self.assertEqual(result.records[0].cadence, 90)
        self.assertEqual(result.records[-1].timestamp, 50.0)
        self.assertEqual(result.records[-1].power, 165)
        self.assertEqual(result.records[-1].cadence, 80)
        self.assertIn((30.0, 330, 95), _record_tuples(result.records))

    def test_parses_mrc_percent_course_data_using_ftp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trainerroad.mrc"
            path.write_text(
                """
                [COURSE HEADER]
                VERSION = 2
                MINUTES PERCENT
                [END COURSE HEADER]
                [COURSE DATA]
                0.0 50
                5.0 80
                10.0 80
                [END COURSE DATA]
                """,
                encoding="utf-8",
            )

            result = WorkoutFileParser(ftp=250, default_cadence=87).parse(path)

        self.assertEqual(result.format_name, "MRC workout")
        self.assertEqual(
            [(record.timestamp, record.power, record.cadence) for record in result.records],
            [(0.0, 125, 87), (300.0, 200, 87), (600.0, 200, 87)],
        )

    def test_parses_erg_watt_course_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "xert.erg"
            path.write_text(
                """
                [COURSE HEADER]
                VERSION = 2
                MINUTES WATTS
                [END COURSE HEADER]
                [COURSE DATA]
                0.0 140
                1.5 220
                [END COURSE DATA]
                """,
                encoding="utf-8",
            )

            result = WorkoutFileParser(ftp=250).parse(path)

        self.assertEqual(result.format_name, "ERG workout")
        self.assertEqual(
            [(record.timestamp, record.power) for record in result.records],
            [(0.0, 140), (90.0, 220)],
        )

    def test_rejects_workout_without_supported_steps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "empty.zwo"
            path.write_text("<workout_file><workout /></workout_file>", encoding="utf-8")

            with self.assertRaises(WorkoutParseError):
                WorkoutFileParser().parse(path)


def _record_tuples(records):
    return [(record.timestamp, record.power, record.cadence) for record in records]


if __name__ == "__main__":
    unittest.main()
