"""Movement model — the etch-a-sketch core.

Converts dial *ticks* (usually +/-1 per detent) into pixel deltas, applying:
  * pixels_per_tick scaling,
  * optional per-axis inversion,
  * optional acceleration: ticks arriving close together on the same axis scale
    up (slow turns precise, fast spins traverse quickly).

This module is **pure logic**: timestamps are passed in, so it is fully
deterministic and unit-testable with no clock and no display. State is exactly
three floats (last-tick time per axis) — fixed size, cannot leak.

Acceleration shape: with dt = time since the previous tick on this axis,
  dt >= window  -> factor 1.0 (no acceleration)
  dt -> 0       -> factor -> max_factor
  in between    -> linear: factor = 1 + (max-1) * (1 - dt/window)
This gives a smooth ramp that is exactly 1x at the window edge and at most
max_factor for back-to-back ticks.
"""

from __future__ import annotations

from dataclasses import dataclass

AXIS_X = "x"
AXIS_Y = "y"


@dataclass
class MovementState:
    last_x: float = -1e9
    last_y: float = -1e9


class MovementModel:
    """Stateful tick->pixel translator (state is just the last-tick times)."""

    def __init__(
        self,
        pixels_per_tick: int = 6,
        invert_x: bool = False,
        invert_y: bool = False,
        accel_enabled: bool = True,
        accel_window_ms: float = 40.0,
        accel_max: float = 4.0,
        scroll_lines_per_tick: int = 1,
        scroll_invert: bool = False,
    ) -> None:
        self.pixels_per_tick = max(1, int(pixels_per_tick))
        self.invert_x = bool(invert_x)
        self.invert_y = bool(invert_y)
        self.accel_enabled = bool(accel_enabled)
        self.accel_window_s = max(0.001, float(accel_window_ms) / 1000.0)
        self.accel_max = max(1.0, float(accel_max))
        self.scroll_lines_per_tick = max(1, int(scroll_lines_per_tick))
        self.scroll_invert = bool(scroll_invert)
        self._state = MovementState()

    # -- runtime adjustment (dials 4/5 will drive these in a later step) ----

    def adjust_sensitivity(self, delta_px: int) -> int:
        self.pixels_per_tick = max(1, min(200, self.pixels_per_tick + int(delta_px)))
        return self.pixels_per_tick

    def adjust_scroll_speed(self, delta: int) -> int:
        self.scroll_lines_per_tick = max(1, min(50, self.scroll_lines_per_tick + int(delta)))
        return self.scroll_lines_per_tick

    # -- core translation ---------------------------------------------------

    def _accel_factor(self, dt: float) -> float:
        if not self.accel_enabled or dt >= self.accel_window_s:
            return 1.0
        if dt < 0:
            dt = 0.0
        return 1.0 + (self.accel_max - 1.0) * (1.0 - dt / self.accel_window_s)

    def tick_to_pixels(self, axis: str, ticks: int, now: float) -> int:
        """Translate ``ticks`` on ``axis`` at time ``now`` (seconds) to pixels."""
        if ticks == 0:
            return 0
        if axis == AXIS_X:
            last = self._state.last_x
            self._state.last_x = now
            invert = self.invert_x
        elif axis == AXIS_Y:
            last = self._state.last_y
            self._state.last_y = now
            invert = self.invert_y
        else:
            raise ValueError(f"unknown axis {axis!r}")

        factor = self._accel_factor(now - last)
        signed = -ticks if invert else ticks
        pixels = signed * self.pixels_per_tick * factor
        # Never let a non-zero tick round down to no motion.
        result = int(round(pixels))
        if result == 0:
            result = 1 if signed > 0 else -1
        return result

    def scroll_to_lines(self, ticks: int) -> int:
        """Translate scroll ticks to wheel lines (no acceleration on scroll)."""
        if ticks == 0:
            return 0
        signed = -ticks if self.scroll_invert else ticks
        return signed * self.scroll_lines_per_tick
