"""HID event translator — Plus dial/key/touch events -> shared event core.

This is the decoding brain of Direct HID mode, and the reason HID and Receiver
mode behave identically: both front-ends ultimately call the *same* EventCore
methods. The OSC receiver turns datagrams into those calls; this turns physical
dial rotations and presses into the very same calls.

It is deliberately pure and device-free — you hand it a core (real or mock) and
feed it ``(dial, is_turn, value)`` tuples — so the whole dial map is unit-testable
with no Stream Deck attached. The actual USB reading lives in hid_frontend.py.

The dial map matches the spec (config-driven, fully remappable):

    Dial 1  turn -> Mouse Y      press -> Left button
    Dial 2  turn -> Mouse X      press -> Right button
    Dial 3  turn -> Scroll       press -> Middle button
    Dial 4  turn -> Sensitivity  press -> reset sensitivity
    Dial 5  turn -> Scroll speed press -> toggle scroll direction
    Dial 6  turn -> (none)       press -> Pause/resume (kill switch)
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .logsetup import get_logger
from .movement import AXIS_X, AXIS_Y

# Allowed action vocabulary (validated by config; unknown -> "none").
TURN_ACTIONS = {"move_x", "move_y", "scroll", "sensitivity", "scrollspeed", "none"}
PRESS_ACTIONS = {"button_left", "button_right", "button_middle", "pause_toggle",
                 "sensitivity_reset", "scroll_invert", "draglock", "none"}


class HidEventTranslator:
    def __init__(
        self,
        core,
        dials: Optional[List[dict]] = None,
        invert: Optional[List[bool]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._core = core
        self._dials = list(dials or [])
        self._invert = list(invert or [])
        self._log = logger or get_logger()

    # -- dial --------------------------------------------------------------

    def on_dial(self, dial: int, is_turn: bool, value) -> None:
        if dial < 0 or dial >= len(self._dials):
            self._log.debug("Dial %s has no mapping; ignored.", dial)
            return
        spec = self._dials[dial]
        if is_turn:
            self._do_turn(dial, spec.get("turn", "none"), int(value))
        else:
            self._do_press(spec.get("press", "none"), bool(value))

    def _do_turn(self, dial: int, action: str, ticks: int) -> None:
        if ticks == 0 or action == "none":
            return
        if dial < len(self._invert) and self._invert[dial]:
            ticks = -ticks
        if action == "move_y":
            self._core.move(AXIS_Y, ticks)
        elif action == "move_x":
            self._core.move(AXIS_X, ticks)
        elif action == "scroll":
            self._core.scroll(ticks)
        elif action == "sensitivity":
            self._core.adjust_sensitivity(ticks)
        elif action == "scrollspeed":
            self._core.adjust_scroll_speed(ticks)

    def _do_press(self, action: str, pressed: bool) -> None:
        # Buttons follow press/release (drag-capable). Everything else is a
        # one-shot that fires on the press edge only.
        if action == "button_left":
            self._core.button("left", pressed)
        elif action == "button_right":
            self._core.button("right", pressed)
        elif action == "button_middle":
            self._core.button("middle", pressed)
        elif pressed:
            if action == "pause_toggle":
                self._core.toggle_enabled()
            elif action == "sensitivity_reset":
                self._core.reset_sensitivity()
            elif action == "scroll_invert":
                self._core.toggle_scroll_invert()
            elif action == "draglock":
                self._core.draglock_toggle()

    # -- keys / touch (logged for discovery; unbound by default) -----------

    def on_key(self, key: int, pressed: bool) -> None:
        # In standalone HID mode there is no Companion paging, so deck keys are
        # unbound by default. Logged so --hid-test reveals their indices; binding
        # them to actions is a future config addition.
        self._log.debug("Deck key %d %s (unbound).", key, "down" if pressed else "up")

    def on_touch(self, event, value) -> None:
        self._log.debug("Touch strip event %s %r (unbound).",
                        getattr(event, "name", event), value)
