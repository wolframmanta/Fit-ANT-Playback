import unittest

from fit_ant_playback_core.ant_protocol import (
    ANTProtocolError,
    BikePowerPageBuilder,
    build_message,
    parse_message,
    parse_messages,
)


class AntProtocolTests(unittest.TestCase):
    def test_build_message_adds_checksum(self):
        self.assertEqual(build_message(0x45, bytes([0x00, 0x39])), bytes.fromhex("a402450039da"))

    def test_parse_message_validates_and_extracts_payload(self):
        message = parse_message(bytes.fromhex("a402450039da"))

        self.assertEqual(message.message_id, 0x45)
        self.assertEqual(message.data, bytes([0x00, 0x39]))

    def test_parse_message_rejects_bad_checksum(self):
        with self.assertRaises(ANTProtocolError):
            parse_message(bytes.fromhex("a40245003900"))

    def test_parse_messages_skips_junk_and_preserves_incomplete_tail(self):
        complete = build_message(0x4B, bytes([0x00]))
        partial = build_message(0x45, bytes([0x00, 0x39]))[:3]

        messages, remaining = parse_messages(b"\x00\xff" + complete + partial)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].message_id, 0x4B)
        self.assertEqual(remaining, partial)

    def test_parse_messages_skips_corrupt_frame(self):
        good = build_message(0x4B, bytes([0x00]))

        messages, remaining = parse_messages(bytes.fromhex("a40245003900") + good)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].message_id, 0x4B)
        self.assertEqual(remaining, b"")

    def test_bike_power_page_clamps_and_rolls_over(self):
        builder = BikePowerPageBuilder()
        builder.event_count = 0xFF
        builder.accumulated_power = 65530

        broadcast = builder.build(power=10, cadence=300)

        self.assertEqual(broadcast.event_count, 0)
        self.assertEqual(broadcast.accumulated_power, 4)
        self.assertEqual(broadcast.page, bytes([0x10, 0x00, 0xFF, 0xFE, 0x04, 0x00, 0x0A, 0x00]))


if __name__ == "__main__":
    unittest.main()
