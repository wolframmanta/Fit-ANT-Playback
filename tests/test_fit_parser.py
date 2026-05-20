import datetime as dt
import unittest
from unittest.mock import patch

from fit_ant_playback_core import fit_parser


class FakeField:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class FakeFitDataMessage:
    def __init__(self, fields):
        self.name = "record"
        self.fields = fields


class FakeFitReader:
    def __init__(self, _filepath):
        start = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        self.frames = [
            FakeFitDataMessage(
                [
                    FakeField("timestamp", start),
                    FakeField("power", 200),
                    FakeField("cadence", 90),
                ]
            ),
            FakeFitDataMessage(
                [
                    FakeField("timestamp", start + dt.timedelta(seconds=1)),
                    FakeField("power", 210),
                ]
            ),
            FakeFitDataMessage(
                [
                    FakeField("timestamp", start + dt.timedelta(seconds=2)),
                    FakeField("cadence", 91),
                ]
            ),
        ]

    def __enter__(self):
        return iter(self.frames)

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeFitDecode:
    FitDataMessage = FakeFitDataMessage
    FitReader = FakeFitReader


class FitParserTests(unittest.TestCase):
    def test_missing_values_hold_last_known_value_by_default(self):
        with patch.object(fit_parser, "fitdecode", FakeFitDecode):
            records = fit_parser.FitFileParser().parse("activity.fit")

        self.assertEqual([record.timestamp for record in records], [0.0, 1.0, 2.0])
        self.assertEqual([(record.power, record.cadence) for record in records], [(200, 90), (210, 90), (210, 91)])

    def test_missing_values_can_be_zero_filled(self):
        with patch.object(fit_parser, "fitdecode", FakeFitDecode):
            records = fit_parser.FitFileParser(missing_value_mode="zero").parse("activity.fit")

        self.assertEqual([(record.power, record.cadence) for record in records], [(200, 90), (210, 0), (0, 91)])


if __name__ == "__main__":
    unittest.main()
