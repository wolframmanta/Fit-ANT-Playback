from __future__ import annotations

from dataclasses import dataclass

SYNC_BYTE = 0xA4

DEVICE_TYPE_BIKE_POWER = 0x0B
DEVICE_NUMBER_DEFAULT = 12345
TRANSMISSION_TYPE_INDEPENDENT = 0x05
CHANNEL_PERIOD_BIKE_POWER = 8182
CHANNEL_FREQUENCY_ANT_PLUS = 57
ANT_PLUS_NETWORK_KEY = bytes([0xB9, 0xA5, 0x21, 0xFB, 0xBD, 0x72, 0xC3, 0x45])

MSG_SYSTEM_RESET = 0x4A
MSG_SET_NETWORK_KEY = 0x46
MSG_ASSIGN_CHANNEL = 0x42
MSG_SET_CHANNEL_ID = 0x51
MSG_SET_CHANNEL_PERIOD = 0x43
MSG_SET_CHANNEL_FREQ = 0x45
MSG_OPEN_CHANNEL = 0x4B
MSG_CLOSE_CHANNEL = 0x4C
MSG_BROADCAST_DATA = 0x4E
MSG_CHANNEL_RESPONSE = 0x40
MSG_STARTUP = 0x6F

CHANNEL_TYPE_BIDIRECTIONAL_TRANSMIT = 0x10
RESPONSE_NO_ERROR = 0x00

RESPONSE_CODES = {
    0x00: "no error",
    0x01: "event RX search timeout",
    0x02: "event RX fail",
    0x03: "event TX",
    0x04: "event transfer RX failed",
    0x05: "event transfer TX complete",
    0x06: "event transfer TX failed",
    0x07: "event channel closed",
    0x08: "event RX fail go to search",
    0x09: "event channel collision",
    0x15: "channel in wrong state",
    0x18: "channel not opened",
    0x19: "channel ID not set",
    0x1F: "transfer in progress",
    0x20: "transfer sequence number error",
    0x21: "transfer in error",
    0x28: "message size exceeds limit",
    0x29: "invalid message",
    0x30: "invalid network number",
    0x31: "invalid list ID",
    0x33: "invalid scan TX channel",
    0x40: "invalid parameter",
    0x41: "event serial queue overflow",
    0x42: "event queue overflow",
    0x43: "encrypt negotiation success",
    0x44: "encrypt negotiation fail",
}


class ANTProtocolError(RuntimeError):
    """Raised when an ANT serial frame is malformed."""


class ANTCommandError(RuntimeError):
    """Raised when an ANT command response reports a failure."""

    def __init__(self, command_id: int, response_code: int) -> None:
        self.command_id = command_id
        self.response_code = response_code
        response = RESPONSE_CODES.get(response_code, f"unknown response 0x{response_code:02X}")
        super().__init__(f"ANT command 0x{command_id:02X} failed: {response}")


@dataclass(frozen=True)
class ANTMessage:
    message_id: int
    data: bytes


@dataclass(frozen=True)
class BikePowerBroadcast:
    page: bytes
    power: int
    cadence: int
    event_count: int
    accumulated_power: int


class BikePowerPageBuilder:
    """Builds ANT+ Bike Power standard power-only data pages."""

    def __init__(self) -> None:
        self.event_count = 0
        self.accumulated_power = 0

    def build(self, power: int, cadence: int) -> BikePowerBroadcast:
        power = clamp(power, 0, 65535)
        cadence = clamp(cadence, 0, 254)
        self.event_count = (self.event_count + 1) & 0xFF
        self.accumulated_power = (self.accumulated_power + power) & 0xFFFF

        page = build_bike_power_page(
            power=power,
            cadence=cadence,
            event_count=self.event_count,
            accumulated_power=self.accumulated_power,
        )
        return BikePowerBroadcast(
            page=page,
            power=power,
            cadence=cadence,
            event_count=self.event_count,
            accumulated_power=self.accumulated_power,
        )


def clamp(value: int, minimum: int, maximum: int) -> int:
    return min(max(int(value), minimum), maximum)


def checksum(frame_without_checksum: bytes) -> int:
    value = 0
    for byte in frame_without_checksum:
        value ^= byte
    return value


def build_message(message_id: int, data: bytes) -> bytes:
    if not 0 <= message_id <= 0xFF:
        raise ValueError("message_id must be one byte")
    if len(data) > 0xFF:
        raise ValueError("ANT message payload is too long")

    frame = bytes([SYNC_BYTE, len(data), message_id]) + bytes(data)
    return frame + bytes([checksum(frame)])


def parse_message(frame: bytes) -> ANTMessage:
    if len(frame) < 4:
        raise ANTProtocolError("ANT frame is too short")
    if frame[0] != SYNC_BYTE:
        raise ANTProtocolError("ANT frame has an invalid sync byte")

    payload_length = frame[1]
    expected_length = payload_length + 4
    if len(frame) != expected_length:
        raise ANTProtocolError(
            f"ANT frame length mismatch: expected {expected_length}, got {len(frame)}"
        )
    if checksum(frame) != 0:
        raise ANTProtocolError("ANT frame checksum mismatch")

    return ANTMessage(message_id=frame[2], data=frame[3:-1])


def parse_messages(buffer: bytes) -> tuple[list[ANTMessage], bytes]:
    messages: list[ANTMessage] = []
    cursor = 0

    while cursor < len(buffer):
        if buffer[cursor] != SYNC_BYTE:
            cursor += 1
            continue

        if len(buffer) - cursor < 4:
            break

        payload_length = buffer[cursor + 1]
        frame_length = payload_length + 4
        if len(buffer) - cursor < frame_length:
            break

        frame = buffer[cursor : cursor + frame_length]
        try:
            messages.append(parse_message(frame))
        except ANTProtocolError:
            cursor += 1
            continue
        cursor += frame_length

    return messages, buffer[cursor:]


def build_bike_power_page(
    *,
    power: int,
    cadence: int,
    event_count: int,
    accumulated_power: int,
) -> bytes:
    power = clamp(power, 0, 65535)
    cadence = clamp(cadence, 0, 254)
    event_count = clamp(event_count, 0, 255)
    accumulated_power = clamp(accumulated_power, 0, 65535)

    return bytes(
        [
            0x10,
            event_count,
            0xFF,
            cadence,
            accumulated_power & 0xFF,
            (accumulated_power >> 8) & 0xFF,
            power & 0xFF,
            (power >> 8) & 0xFF,
        ]
    )
