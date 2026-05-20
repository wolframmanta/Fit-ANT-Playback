from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .ant_protocol import CHANNEL_PERIOD_BIKE_POWER
from .models import PowerCadenceRecord

BROADCAST_HZ = 32768 / CHANNEL_PERIOD_BIKE_POWER


class FitPlaybackEngine:
    """Replays FIT records while broadcasting at the ANT+ channel rate."""

    def __init__(
        self,
        *,
        records: list[PowerCadenceRecord],
        broadcast: Callable[[PowerCadenceRecord], None],
        on_update: Callable[[PowerCadenceRecord, float, int], None],
        on_finished: Callable[[], None],
        on_error: Callable[[Exception], None],
        speed: float = 1.0,
        tick_hz: float = BROADCAST_HZ,
    ) -> None:
        if not records:
            raise ValueError("records must not be empty")
        if speed <= 0:
            raise ValueError("speed must be greater than zero")
        if tick_hz <= 0:
            raise ValueError("tick_hz must be greater than zero")
        self.records = records
        self.broadcast = broadcast
        self.on_update = on_update
        self.on_finished = on_finished
        self.on_error = on_error
        self.tick_hz = tick_hz
        self._speed = speed
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._paused.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def stop(self, *, join: bool = True) -> None:
        self._stop.set()
        self._paused.clear()
        if (
            join
            and self._thread
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
        ):
            self._thread.join(timeout=1.0)

    def set_speed(self, speed: float) -> None:
        if speed <= 0:
            raise ValueError("speed must be greater than zero")
        with self._lock:
            self._speed = speed

    def _current_speed(self) -> float:
        with self._lock:
            return self._speed

    def _run(self) -> None:
        total_duration = self.records[-1].timestamp
        current_index = 0
        source_time = self.records[0].timestamp
        last_wall = time.monotonic()
        tick_interval = 1 / self.tick_hz
        next_tick = last_wall

        try:
            while not self._stop.is_set():
                now = time.monotonic()

                if self._paused.is_set():
                    last_wall = now
                    next_tick = now + tick_interval
                    time.sleep(0.05)
                    continue

                elapsed = now - last_wall
                last_wall = now
                source_time += elapsed * self._current_speed()

                if now < next_tick:
                    time.sleep(min(next_tick - now, 0.05))
                    continue

                while (
                    current_index + 1 < len(self.records)
                    and self.records[current_index + 1].timestamp <= source_time
                ):
                    current_index += 1

                record = self.records[current_index]
                self.broadcast(record)
                self.on_update(record, total_duration, current_index)

                if source_time >= total_duration and current_index >= len(self.records) - 1:
                    break

                next_tick += tick_interval
                if next_tick < time.monotonic() - tick_interval:
                    next_tick = time.monotonic() + tick_interval

        except Exception as exc:
            self.on_error(exc)
            return

        if not self._stop.is_set():
            self.on_finished()


class ManualBroadcastEngine:
    """Broadcasts manually supplied power and cadence at a stable tick rate."""

    def __init__(
        self,
        *,
        get_values: Callable[[], tuple[int, int]],
        broadcast: Callable[[int, int], None],
        on_update: Callable[[int, int], None],
        on_error: Callable[[Exception], None],
        tick_hz: float = BROADCAST_HZ,
    ) -> None:
        if tick_hz <= 0:
            raise ValueError("tick_hz must be greater than zero")
        self.get_values = get_values
        self.broadcast = broadcast
        self.on_update = on_update
        self.on_error = on_error
        self.tick_hz = tick_hz
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, *, join: bool = True) -> None:
        self._stop.set()
        if (
            join
            and self._thread
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
        ):
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        tick_interval = 1 / self.tick_hz
        next_tick = time.monotonic()

        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now < next_tick:
                    time.sleep(min(next_tick - now, 0.05))
                    continue

                power, cadence = self.get_values()
                self.broadcast(power, cadence)
                self.on_update(power, cadence)

                next_tick += tick_interval
                if next_tick < time.monotonic() - tick_interval:
                    next_tick = time.monotonic() + tick_interval

        except Exception as exc:
            self.on_error(exc)
