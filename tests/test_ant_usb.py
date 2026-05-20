import unittest

from fit_ant_playback_core.ant_protocol import (
    ANTCommandError,
    MSG_BROADCAST_DATA,
    MSG_CHANNEL_RESPONSE,
    MSG_OPEN_CHANNEL,
    build_message,
    parse_message,
)
from fit_ant_playback_core.ant_usb import AntUsbBroadcaster


class FakeInEndpoint:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read(self, _size, _timeout):
        if not self.chunks:
            raise TimeoutError("no data")
        return self.chunks.pop(0)


class FakeOutEndpoint:
    def __init__(self):
        self.writes = []

    def write(self, frame, _timeout):
        self.writes.append(bytes(frame))


class AntUsbTests(unittest.TestCase):
    def test_wait_for_command_response_accepts_no_error(self):
        response = build_message(MSG_CHANNEL_RESPONSE, bytes([0x00, MSG_OPEN_CHANNEL, 0x00]))
        broadcaster = AntUsbBroadcaster()
        broadcaster.ep_in = FakeInEndpoint([response])

        broadcaster._wait_for_command_response(MSG_OPEN_CHANNEL, timeout_ms=100)

    def test_wait_for_command_response_raises_command_error(self):
        response = build_message(MSG_CHANNEL_RESPONSE, bytes([0x00, MSG_OPEN_CHANNEL, 0x15]))
        broadcaster = AntUsbBroadcaster()
        broadcaster.ep_in = FakeInEndpoint([response])

        with self.assertRaises(ANTCommandError):
            broadcaster._wait_for_command_response(MSG_OPEN_CHANNEL, timeout_ms=100)

    def test_broadcast_writes_channel_prefixed_bike_power_page(self):
        broadcaster = AntUsbBroadcaster()
        broadcaster.running = True
        broadcaster.ep_out = FakeOutEndpoint()

        broadcaster.broadcast_power_cadence(250, 90)

        message = parse_message(broadcaster.ep_out.writes[0])
        self.assertEqual(message.message_id, MSG_BROADCAST_DATA)
        self.assertEqual(message.data, bytes([0x00, 0x10, 0x01, 0xFF, 90, 250, 0, 250, 0]))


if __name__ == "__main__":
    unittest.main()
