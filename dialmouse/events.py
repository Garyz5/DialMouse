"""Event core — the shared front-end-to-back-end bridge.

Both input front-ends (the OSC receiver now, the optional HID reader later) call
into this object with abstract events. The core converts ticks to pixels via the
movement model and drives the mouse back-end and confinement controller. Keeping
this separate is what lets Receiver mode and Direct HID mode share identical
behavior.

The ``enabled`` flag is the Pause/kill-switch (dial 6): when paused, pointer and
button events are ignored so the dials behave as normal Companion controls,
while control/confine events still work so you can resume.

No state grows here: the movement model holds three timestamps, and the core
holds a handful of flags. Nothing accumulates.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .confine import ConfineController
from .logsetup import get_logger
from .mouse_backend import MouseBackend
from .movement import AXIS_X, AXIS_Y, MovementModel

# Defensive clamp on incoming tick magnitudes. A single detent is +/-1; anything
# wildly larger is malformed or hostile, so we clamp to keep the cursor sane.
MAX_TICKS = 127


def _clamp_ticks(value: int) -> int:
    if value > MAX_TICKS:
        return MAX_TICKS
    if value < -MAX_TICKS:
        return -MAX_TICKS
    return value


class EventCore:
    def __init__(
        self,
        movement: MovementModel,
        backend: MouseBackend,
        confine: ConfineController,
        enabled: bool = True,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._movement = movement
        self._backend = backend
        self._confine = confine
        self._enabled = enabled
        self._log = logger or get_logger()

    @property
    def enabled(self) -> bool:
        return self._enabled

    # -- pointer -----------------------------------------------------------

    def move(self, axis: str, ticks: int) -> None:
        if not self._enabled:
            return
        ticks = _clamp_ticks(int(ticks))
        if ticks == 0:
            return
        px = self._movement.tick_to_pixels(axis, ticks, time.monotonic())
        if axis == AXIS_X:
            self._backend.move_relative(px, 0)
        else:
            self._backend.move_relative(0, px)

    def scroll(self, ticks: int) -> None:
        if not self._enabled:
            return
        ticks = _clamp_ticks(int(ticks))
        if ticks == 0:
            return
        lines = self._movement.scroll_to_lines(ticks)
        # pynput: positive dy scrolls up; our "scroll +" means down, so negate.
        self._backend.scroll(0, -lines)

    # -- buttons -----------------------------------------------------------

    def button(self, name: str, down: bool) -> None:
        if not self._enabled:
            return
        if down:
            self._backend.button_down(name)
        else:
            self._backend.button_up(name)

    def click(self, name: str) -> None:
        if not self._enabled:
            return
        self._backend.click(name, 1)

    # -- sensitivity / scroll speed ---------------------------------------

    def adjust_sensitivity(self, delta: int) -> None:
        v = self._movement.adjust_sensitivity(int(delta))
        self._log.info("Sensitivity: %d px/tick.", v)

    def adjust_scroll_speed(self, delta: int) -> None:
        v = self._movement.adjust_scroll_speed(int(delta))
        self._log.info("Scroll speed: %d lines/tick.", v)

    # -- control (pause / resume) -----------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._log.info("DialMouse %s.", "resumed" if self._enabled else "paused (dials pass through)")

    def toggle_enabled(self) -> None:
        self.set_enabled(not self._enabled)

    # -- confinement -------------------------------------------------------

    def confine_minimon(self) -> None:
        if self._confine.enable():
            self._snap_into_region()

    def confine_off(self) -> None:
        self._confine.disable()

    def confine_toggle(self) -> None:
        if self._confine.toggle():
            self._snap_into_region()

    def park(self) -> None:
        target = self._confine.park_target()
        if target is not None:
            self._backend.move_to(*target)
            self._log.debug("Parked cursor at Mini Mon centre %s.", target)
        else:
            self._log.warning("Park: no Mini Mon resolved.")

    def _snap_into_region(self) -> None:
        # Pull the cursor into the Mini Mon when confinement engages, so it isn't
        # stranded on another screen behind an invisible wall.
        target = self._confine.park_target()
        if target is not None:
            try:
                self._backend.move_to(*target)
            except Exception as exc:  # pragma: no cover - injection guard
                self._log.debug("Snap-into-region skipped: %s", exc)
