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
        keyboard=None,
        display=None,
        feedback=None,
    ) -> None:
        self._movement = movement
        self._backend = backend
        self._confine = confine
        self._enabled = enabled
        self._log = logger or get_logger()
        # Keyboard controller (Step 4). Optional so existing call sites and tests
        # that only exercise the mouse path keep working.
        self._keyboard = keyboard
        # Display controller + return-channel feedback (Step 5). Both optional;
        # the core functions identically whether or not feedback is wired.
        self._display = display
        self._feedback = feedback
        # Drag-lock: when latched, the left button is held down until toggled off
        # so you can drag long distances without holding a dial.
        self._drag_locked = False

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

    def click_double(self) -> None:
        if not self._enabled:
            return
        self._backend.click("left", 2)

    def draglock_toggle(self) -> None:
        """Latch the left button down, or release it. Survives across moves."""
        if not self._enabled:
            return
        if self._drag_locked:
            self._backend.button_up("left")
            self._drag_locked = False
            self._log.info("Drag-lock released.")
        else:
            self._backend.button_down("left")
            self._drag_locked = True
            self._log.info("Drag-lock engaged (left button held).")

    # -- sensitivity / scroll speed ---------------------------------------

    def adjust_sensitivity(self, delta: int) -> None:
        v = self._movement.adjust_sensitivity(int(delta))
        self._log.info("Sensitivity: %d px/tick.", v)

    def adjust_scroll_speed(self, delta: int) -> None:
        v = self._movement.adjust_scroll_speed(int(delta))
        self._log.info("Scroll speed: %d lines/tick.", v)

    def sensitivity_preset(self, n: int) -> None:
        v = self._movement.set_sensitivity_preset(int(n))
        self._log.info("Sensitivity preset %d -> %d px/tick.", int(n), v)

    def set_precision(self, on: bool) -> None:
        self._movement.set_precision(bool(on))
        self._log.debug("Precision mode %s.", "on" if on else "off")

    def set_turbo(self, on: bool) -> None:
        self._movement.set_turbo(bool(on))
        self._log.debug("Turbo mode %s.", "on" if on else "off")

    # -- keyboard (Step 4) -------------------------------------------------

    def key_tap(self, name: str) -> None:
        if not self._enabled or self._keyboard is None:
            return
        self._keyboard.tap(name)

    def key_down(self, name: str) -> None:
        if not self._enabled or self._keyboard is None:
            return
        self._keyboard.key_down(name)

    def key_up(self, name: str) -> None:
        if not self._enabled or self._keyboard is None:
            return
        self._keyboard.key_up(name)

    def key_type(self, text: str) -> None:
        if not self._enabled or self._keyboard is None:
            return
        self._keyboard.type_text(text)

    def key_mod_toggle(self, name: str) -> None:
        # Allowed even when paused: it only flips internal latch state and
        # injects nothing, so the shift indicator stays usable.
        if self._keyboard is None:
            return
        self._keyboard.mod_toggle(name)
        if self._feedback is not None:
            self._feedback.shift_state(self._keyboard.shift_latched)

    def key_snippet(self, n: int) -> None:
        if not self._enabled or self._keyboard is None:
            return
        self._keyboard.snippet(int(n))

    # -- control (pause / resume) -----------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        # Safety: if we are pausing while drag-lock holds the left button down,
        # release it so the button can never be stranded by the kill-switch.
        if not self._enabled and self._drag_locked:
            try:
                self._backend.button_up("left")
            except Exception as exc:  # pragma: no cover - injection guard
                self._log.debug("Drag-lock release on pause skipped: %s", exc)
            self._drag_locked = False
            self._log.info("Drag-lock released by pause.")
        self._log.info("DialMouse %s.", "resumed" if self._enabled else "paused (dials pass through)")

    def toggle_enabled(self) -> None:
        self.set_enabled(not self._enabled)

    # -- confinement -------------------------------------------------------

    def confine_minimon(self) -> None:
        if self._confine.enable():
            self._snap_into_region()
        self._publish_confine()

    def confine_off(self) -> None:
        self._confine.disable()
        self._publish_confine()

    def confine_toggle(self) -> None:
        if self._confine.toggle():
            self._snap_into_region()
        self._publish_confine()

    def park(self) -> None:
        target = self._confine.park_target()
        if target is not None:
            self._backend.move_to(*target)
            self._log.debug("Parked cursor at Mini Mon centre %s.", target)
        else:
            self._log.warning("Park: no Mini Mon resolved.")

    # -- display control (Step 5) -----------------------------------------

    def display_arm(self) -> None:
        if self._display is None:
            return
        self._display.arm()
        self._publish_armed()

    def display_pick(self, n: int) -> None:
        if self._display is None:
            return
        self._display.pick(int(n))
        self._publish_armed()
        self._publish_confine()   # a switch may have moved the Mini Mon

    def display_extend(self) -> None:
        if self._display is None:
            return
        self._display.extend()
        self._publish_armed()
        self._publish_confine()

    def display_duplicate(self) -> None:
        if self._display is None:
            return
        self._display.duplicate()
        self._publish_confine()

    def display_panic(self) -> None:
        if self._display is None:
            return
        self._display.panic()
        self._publish_armed()
        self._publish_confine()

    def display_preset(self, name: str) -> None:
        if self._display is None:
            return
        self._display.preset(name)
        self._publish_confine()

    def display_identify(self) -> None:
        if self._display is None:
            return
        self._display.identify()

    # -- return-channel feedback ------------------------------------------

    def publish_state(self) -> None:
        """Push the current state to Companion (called once at startup)."""
        if self._feedback is None:
            return
        self._publish_confine()
        self._publish_armed()
        if self._keyboard is not None:
            self._feedback.shift_state(self._keyboard.shift_latched)
        if self._display is not None:
            self._feedback.display_count(self._display.display_count())

    def _publish_confine(self) -> None:
        if self._feedback is not None:
            self._feedback.confine_state(self._confine.is_confined)

    def _publish_armed(self) -> None:
        if self._feedback is not None and self._display is not None:
            self._feedback.display_armed(self._display.armed)

    def _snap_into_region(self) -> None:
        # Pull the cursor into the Mini Mon when confinement engages, so it isn't
        # stranded on another screen behind an invisible wall.
        target = self._confine.park_target()
        if target is not None:
            try:
                self._backend.move_to(*target)
            except Exception as exc:  # pragma: no cover - injection guard
                self._log.debug("Snap-into-region skipped: %s", exc)
