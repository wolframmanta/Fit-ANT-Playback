from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .ant_protocol import (
    ANTCommandError,
    ANT_PLUS_NETWORK_KEY,
    CHANNEL_FREQUENCY_ANT_PLUS,
    CHANNEL_PERIOD_BIKE_POWER,
    CHANNEL_TYPE_BIDIRECTIONAL_TRANSMIT,
    DEVICE_NUMBER_DEFAULT,
    DEVICE_TYPE_BIKE_POWER,
    MSG_ASSIGN_CHANNEL,
    MSG_BROADCAST_DATA,
    MSG_CHANNEL_RESPONSE,
    MSG_CLOSE_CHANNEL,
    MSG_OPEN_CHANNEL,
    MSG_SET_CHANNEL_FREQ,
    MSG_SET_CHANNEL_ID,
    MSG_SET_CHANNEL_PERIOD,
    MSG_SET_NETWORK_KEY,
    MSG_STARTUP,
    MSG_SYSTEM_RESET,
    RESPONSE_NO_ERROR,
    TRANSMISSION_TYPE_INDEPENDENT,
    BikePowerPageBuilder,
    build_message,
    parse_messages,
)

ANT_STICK_IDS = (
    (0x0FCF, 0x1008, "Dynastream ANT USB-m Stick"),
    (0x0FCF, 0x1009, "Dynastream ANT USB2 Stick"),
    (0x0FCF, 0x1004, "Dynastream ANT USB Stick"),
)


class AntUsbError(RuntimeError):
    """Raised for ANT USB initialization or IO failures."""


class AntUsbBroadcaster:
    """Raw USB ANT+ Bike Power broadcaster using PyUSB."""

    DEVICE_TYPE = DEVICE_TYPE_BIKE_POWER
    DEVICE_NUMBER = DEVICE_NUMBER_DEFAULT
    TRANSMISSION_TYPE = TRANSMISSION_TYPE_INDEPENDENT
    CHANNEL_PERIOD = CHANNEL_PERIOD_BIKE_POWER
    CHANNEL_FREQUENCY = CHANNEL_FREQUENCY_ANT_PLUS

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        channel_number: int = 0,
        network_number: int = 0,
    ) -> None:
        self.logger = logger or logging.getLogger("fit_ant_playback")
        self.channel_number = channel_number
        self.network_number = network_number
        self.device: Any = None
        self.ep_out: Any = None
        self.ep_in: Any = None
        self.running = False
        self.last_error: str | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()
        self._io_lock = threading.Lock()
        self._response_buffer = b""
        self._page_builder = BikePowerPageBuilder()

    def start(self) -> bool:
        try:
            self._open_usb_device()
            self._configure_ant_channel()
        except Exception as exc:
            self.last_error = str(exc)
            self.logger.error("ANT+ connection failed: %s", exc)
            self.stop()
            return False

        self.running = True
        self._stop_reader.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        self.logger.info("ANT+ channel opened successfully")
        self.logger.info("Broadcasting as Device ID %s", self.DEVICE_NUMBER)
        return True

    def stop(self) -> None:
        self._stop_reader.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)

        if self.device and self.ep_out and self.running:
            try:
                self._send_command(
                    MSG_CLOSE_CHANNEL,
                    bytes([self.channel_number]),
                    expect_response=False,
                )
            except Exception as exc:
                self.logger.debug("Ignoring ANT+ close failure: %s", exc)

        self.running = False
        self._release_usb_device()

    def broadcast_power_cadence(self, power: int, cadence: int) -> None:
        if not self.running or not self.ep_out:
            raise AntUsbError("ANT+ broadcaster is not connected")

        broadcast = self._page_builder.build(power, cadence)
        payload = bytes([self.channel_number]) + broadcast.page
        frame = build_message(MSG_BROADCAST_DATA, payload)

        try:
            with self._io_lock:
                self.ep_out.write(frame, 100)
        except Exception as exc:
            self.last_error = str(exc)
            raise AntUsbError(f"ANT+ broadcast failed: {exc}") from exc

    def _open_usb_device(self) -> None:
        try:
            import usb.core  # type: ignore[import-untyped]
            import usb.util  # type: ignore[import-untyped]
        except ImportError as exc:
            raise AntUsbError("PyUSB is not installed. Run: pip install pyusb") from exc

        for vendor_id, product_id, name in ANT_STICK_IDS:
            self.device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
            if self.device:
                self.logger.info("Found %s (VID 0x%04X, PID 0x%04X)", name, vendor_id, product_id)
                break

        if not self.device:
            raise AntUsbError("No ANT+ USB stick found")

        try:
            self.device.reset()
        except Exception as exc:
            self.logger.debug("USB reset warning: %s", exc)

        try:
            if self.device.is_kernel_driver_active(0):
                self.device.detach_kernel_driver(0)
        except Exception:
            pass

        try:
            usb.util.dispose_resources(self.device)
        except Exception:
            pass

        self.device.set_configuration()
        configuration = self.device.get_active_configuration()
        interface = configuration[(0, 0)]

        try:
            usb.util.claim_interface(self.device, interface)
        except Exception as exc:
            self.logger.debug("USB interface claim warning: %s", exc)

        self.ep_out = usb.util.find_descriptor(
            interface,
            custom_match=lambda endpoint: (
                usb.util.endpoint_direction(endpoint.bEndpointAddress) == usb.util.ENDPOINT_OUT
            ),
        )
        self.ep_in = usb.util.find_descriptor(
            interface,
            custom_match=lambda endpoint: (
                usb.util.endpoint_direction(endpoint.bEndpointAddress) == usb.util.ENDPOINT_IN
            ),
        )

        if not self.ep_out or not self.ep_in:
            raise AntUsbError("Could not find ANT+ USB endpoints")

        self.logger.info("USB endpoints configured")
        self._drain_input(timeout_ms=50, max_reads=5)

    def _configure_ant_channel(self) -> None:
        self.logger.info("Resetting ANT system")
        self._write_frame(MSG_SYSTEM_RESET, bytes([0x00]), timeout_ms=1000)
        self._wait_for_startup(timeout_ms=1500)

        self.logger.info("Setting ANT+ network key")
        self._send_command(MSG_SET_NETWORK_KEY, bytes([self.network_number]) + ANT_PLUS_NETWORK_KEY)

        self.logger.info("Assigning transmit channel")
        self._send_command(
            MSG_ASSIGN_CHANNEL,
            bytes(
                [
                    self.channel_number,
                    CHANNEL_TYPE_BIDIRECTIONAL_TRANSMIT,
                    self.network_number,
                ]
            ),
        )

        self.logger.info("Setting channel ID")
        self._send_command(
            MSG_SET_CHANNEL_ID,
            bytes(
                [
                    self.channel_number,
                    self.DEVICE_NUMBER & 0xFF,
                    (self.DEVICE_NUMBER >> 8) & 0xFF,
                    self.DEVICE_TYPE,
                    self.TRANSMISSION_TYPE,
                ]
            ),
        )

        self.logger.info("Setting channel period")
        self._send_command(
            MSG_SET_CHANNEL_PERIOD,
            bytes(
                [
                    self.channel_number,
                    self.CHANNEL_PERIOD & 0xFF,
                    (self.CHANNEL_PERIOD >> 8) & 0xFF,
                ]
            ),
        )

        self.logger.info("Setting RF frequency")
        self._send_command(MSG_SET_CHANNEL_FREQ, bytes([self.channel_number, self.CHANNEL_FREQUENCY]))

        self.logger.info("Opening ANT+ channel")
        self._send_command(MSG_OPEN_CHANNEL, bytes([self.channel_number]))

    def _send_command(
        self,
        message_id: int,
        data: bytes,
        *,
        expect_response: bool = True,
        timeout_ms: int = 1000,
    ) -> None:
        self._write_frame(message_id, data, timeout_ms=timeout_ms)
        if expect_response:
            self._wait_for_command_response(message_id, timeout_ms=timeout_ms)

    def _write_frame(self, message_id: int, data: bytes, *, timeout_ms: int) -> None:
        if not self.ep_out:
            raise AntUsbError("ANT+ USB output endpoint is not available")

        frame = build_message(message_id, data)
        try:
            with self._io_lock:
                self.ep_out.write(frame, timeout_ms)
        except Exception as exc:
            raise AntUsbError(f"USB write failed for ANT message 0x{message_id:02X}: {exc}") from exc

    def _wait_for_startup(self, *, timeout_ms: int) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            for message in self._read_available_messages(timeout_ms=100):
                if message.message_id == MSG_STARTUP:
                    return
        self.logger.debug("No ANT startup message received after reset")

    def _wait_for_command_response(self, command_id: int, *, timeout_ms: int) -> None:
        deadline = time.monotonic() + timeout_ms / 1000

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            for message in self._read_available_messages(timeout_ms=min(100, remaining_ms)):
                if message.message_id != MSG_CHANNEL_RESPONSE or len(message.data) < 3:
                    continue

                response_command = message.data[1]
                response_code = message.data[2]
                if response_command != command_id:
                    continue

                if response_code == RESPONSE_NO_ERROR:
                    return
                raise ANTCommandError(command_id, response_code)

        raise AntUsbError(f"Timed out waiting for ANT response to command 0x{command_id:02X}")

    def _read_available_messages(self, *, timeout_ms: int) -> list[Any]:
        if not self.ep_in:
            return []

        try:
            raw = bytes(self.ep_in.read(64, timeout_ms))
        except Exception:
            return []

        self._response_buffer += raw
        messages, self._response_buffer = parse_messages(self._response_buffer)
        return messages

    def _drain_input(self, *, timeout_ms: int, max_reads: int) -> None:
        for _ in range(max_reads):
            if not self._read_available_messages(timeout_ms=timeout_ms):
                return

    def _reader_loop(self) -> None:
        while not self._stop_reader.is_set():
            try:
                self._read_available_messages(timeout_ms=100)
            except Exception as exc:
                self.logger.debug("ANT+ reader ignored malformed input: %s", exc)

    def _release_usb_device(self) -> None:
        if not self.device:
            self.ep_out = None
            self.ep_in = None
            return

        try:
            import usb.util  # type: ignore[import-untyped]

            usb.util.dispose_resources(self.device)
        except Exception:
            pass
        finally:
            self.device = None
            self.ep_out = None
            self.ep_in = None
