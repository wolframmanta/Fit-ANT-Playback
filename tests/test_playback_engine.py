import threading
import unittest

from fit_ant_playback_core.models import PowerCadenceRecord
from fit_ant_playback_core.playback_engine import FitPlaybackEngine


class PlaybackEngineTests(unittest.TestCase):
    def test_fit_playback_broadcasts_at_tick_rate_and_finishes(self):
        records = [
            PowerCadenceRecord(timestamp=0.0, power=100, cadence=80),
            PowerCadenceRecord(timestamp=0.05, power=200, cadence=90),
        ]
        sent = []
        finished = threading.Event()
        errors = []

        engine = FitPlaybackEngine(
            records=records,
            broadcast=lambda record: sent.append(record),
            on_update=lambda record, total, index: None,
            on_finished=finished.set,
            on_error=errors.append,
            tick_hz=100,
        )

        engine.start()
        self.assertTrue(finished.wait(timeout=1.0))
        engine.stop()

        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(sent), 2)
        self.assertEqual(sent[0].power, 100)
        self.assertEqual(sent[-1].power, 200)


if __name__ == "__main__":
    unittest.main()
