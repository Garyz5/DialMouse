"""Mouse back-end: inject OS-level relative motion, scroll, and button events.

This is the "back-end" half of the event core. In every mode (Receiver or Direct
HID), a front-end emits abstract events and calls into exactly this object, so
injection behaves identically regardless of input source.

Key properties:
  * Relative motion only. We never teleport the cursor to an absolute design
    coordinate; we read the current position, add a delta, clamp to the
    virtual-desktop bounds, and set the result. This is the etch-a-sketch model
    and it crosses multiple monitors naturally.
  * Lazy, guarded initialization. The underlying pynput Controller is created on
    first use. If it can't be created (missing macOS Accessibility permission,
    no display/uinput on Linux), we raise a clear, actionable error instead of a
    cryptic stack trace.
  * No retained state that can grow. The back-end holds only the controller and
    immutable bounds. Nothing accumulates, so it cannot leak.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from . import platform_info
from .logsetup import get_logger
from .virtual_desktop import Bounds, clamp_point, detect_bounds

# Logical button names used throughout DialMouse (config-facing).
BUTTON_LEFT = "left"
BUTTON_RIGHT = "right"
BUTTON_MIDDLE = "middle"
_VALID_BUTTONS = (BUTTON_LEFT, BUTTON_RIGHT, BUTTON_MIDDLE)


class DialMouseInjectionError(RuntimeError):
    """Raised when OS-level mouse injection is unavailable.

    Carries a human-actionable ``guidance`` string describing exactly what to do
    on the current OS (grant Accessibility, add a udev rule, etc.).
    """

    def __init__(self, message: str, guidance: str = "") -> None:
        super().__init__(message)
        self.guidance = guidance


def _permission_guidance(os_name: str) -> str:
    if os_name == platform_info.OS_MACOS:
        return (
            "macOS needs Accessibility permission to move the mouse.\n"
            "  System Settings -> Privacy & Security -> Accessibility -> enable DialMouse\n"
            "  (also check Input Monitoring if movement still fails).\n"
            "  The grant is tied to this exact binary/path, so re-grant if you move it."
        )
    if os_name == platform_info.OS_LINUX:
        session = platform_info.detect_linux_session()
        if session == platform_info.SESSION_WAYLAND:
            return (
                "On Wayland, synthetic input via XTest is blocked; DialMouse needs\n"
                "  write access to /dev/uinput. Add yourself to the 'input' group or\n"
                "  install the provided udev rule, then re-log in. (Step 3 ships the rule.)"
            )
        if session == platform_info.SESSION_NONE:
            return (
                "No display server detected (headless/SSH session). Mouse injection\n"
                "  needs a graphical session (X11 or Wayland)."
            )
        return (
            "Under X11, XTest injection should work out of the box. If it fails,\n"
            "  confirm DISPLAY is set and the python-xlib backend is available."
        )
    if os_name == platform_info.OS_WINDOWS:
        return "Windows uses SendInput and needs no special permission."
    return "Unknown platform; mouse injection support is uncertain."


class MouseBackend:
    """Injects relative mouse motion, scrolling, and button presses."""

    def __init__(
        self,
        bounds: Optional[Bounds] = None,
        auto_detect_bounds: bool = True,
        logger: Optional[logging.Logger] = None,
        region_provider: Optional[Callable[[], Optional[Bounds]]] = None,
    ) -> None:
        self._log = logger or get_logger()
        self._os = platform_info.detect_os()
        self._controller = None  # created lazily in _ensure()
        # If set, region_provider() returns the active confinement region (or
        # None for free roam). When it returns a region we clamp to it instead of
        # the whole virtual desktop, so confine/detach takes effect immediately.
        self._region_provider = region_provider
        if bounds is not None:
            self._bounds = bounds
        elif auto_detect_bounds:
            self._bounds = detect_bounds()
        else:
            self._bounds = None
        self._log.debug(
            "MouseBackend init: os=%s, bounds=%s", self._os,
            self._bounds if self._bounds else "unknown (relying on OS clamp)",
        )

    # -- initialization ----------------------------------------------------

    def _ensure(self):
        """Create the pynput Controller on first use, with clear errors."""
        if self._controller is not None:
            return self._controller
        try:
            from pynput.mouse import Controller  # imported lazily on purpose
        except Exception as exc:  # ImportError or backend import failure
            raise DialMouseInjectionError(
                f"Could not load the mouse-injection backend (pynput): {exc}",
                guidance=_permission_guidance(self._os),
            ) from exc
        try:
            self._controller = Controller()
            # Touch the position once to surface permission errors eagerly,
            # rather than on the first real movement.
            _ = self._controller.position
        except Exception as exc:
            raise DialMouseInjectionError(
                f"Mouse injection is not available on this system: {exc}",
                guidance=_permission_guidance(self._os),
            ) from exc
        self._log.debug("pynput Controller ready.")
        return self._controller

    def preflight(self) -> None:
        """Eagerly verify injection works; raises DialMouseInjectionError if not."""
        self._ensure()

    @property
    def bounds(self) -> Optional[Bounds]:
        return self._bounds

    def _active_bounds(self) -> Optional[Bounds]:
        """Confinement region if one is active, else the virtual-desktop bounds."""
        if self._region_provider is not None:
            region = self._region_provider()
            if region is not None:
                return region
        return self._bounds

    # -- movement ----------------------------------------------------------

    def move_relative(self, dx: float, dy: float) -> None:
        """Move the cursor by (dx, dy) pixels, clamped to the active region."""
        ctrl = self._ensure()
        bounds = self._active_bounds()
        try:
            cur_x, cur_y = ctrl.position
        except Exception:
            # If we can't read the position, fall back to pynput's own relative
            # move (the OS will clamp to the desktop). Note: this path can't
            # enforce a sub-desktop confinement region.
            ctrl.move(int(round(dx)), int(round(dy)))
            return
        nx, ny = clamp_point(cur_x + dx, cur_y + dy, bounds)
        ctrl.position = (nx, ny)

    def move_to(self, x: int, y: int) -> None:
        """Absolute move (clamped). Used only for explicit Park/snap actions."""
        ctrl = self._ensure()
        nx, ny = clamp_point(x, y, self._active_bounds())
        ctrl.position = (nx, ny)

    # -- scrolling ---------------------------------------------------------

    def scroll(self, dx: float, dy: float) -> None:
        """Scroll by (dx, dy) wheel steps. Positive dy scrolls up (pynput)."""
        ctrl = self._ensure()
        ctrl.scroll(int(round(dx)), int(round(dy)))

    # -- buttons -----------------------------------------------------------

    def _button(self, name: str):
        from pynput.mouse import Button
        mapping = {
            BUTTON_LEFT: Button.left,
            BUTTON_RIGHT: Button.right,
            BUTTON_MIDDLE: Button.middle,
        }
        if name not in mapping:
            raise ValueError(f"unknown button {name!r}; expected one of {_VALID_BUTTONS}")
        return mapping[name]

    def button_down(self, name: str) -> None:
        ctrl = self._ensure()
        ctrl.press(self._button(name))

    def button_up(self, name: str) -> None:
        ctrl = self._ensure()
        ctrl.release(self._button(name))

    def click(self, name: str, count: int = 1) -> None:
        ctrl = self._ensure()
        ctrl.click(self._button(name), count)

    # -- self test ---------------------------------------------------------

    def self_test(
        self,
        side: int = 120,
        step: int = 6,
        step_delay: float = 0.006,
        heartbeat: Optional[Callable[[], None]] = None,
        start_at: Optional[tuple] = None,
        demo_bounds: bool = False,
    ) -> None:
        """Draw a visible square with the cursor, then perform one left click.

        This is the ``--test`` self-check: it proves OS-level injection works on
        this machine *before* any Companion wiring. ``heartbeat`` (if given) is
        called between micro-steps to keep the watchdog satisfied. ``start_at``
        moves the cursor to a starting point first (used to begin inside the
        Mini Mon when confinement is active). ``demo_bounds`` additionally rides
        the cursor to each edge of the active region, so confinement is visibly
        obvious (the cursor snaps to the four edges of one screen and never
        leaves it).
        """
        self.preflight()
        if start_at is not None:
            self.move_to(int(start_at[0]), int(start_at[1]))
        region = self._active_bounds()
        self._log.info("Self-test: drawing a %dpx square then one left click%s.",
                       side, " (confined)" if region is not None else "")

        def beat() -> None:
            if heartbeat is not None:
                heartbeat()

        legs = (
            (step, 0),   # right
            (0, step),   # down
            (-step, 0),  # left
            (0, -step),  # up
        )
        for dx, dy in legs:
            travelled = 0
            while travelled < side:
                self.move_relative(dx, dy)
                travelled += abs(dx) + abs(dy)
                beat()
                time.sleep(step_delay)

        time.sleep(0.1)
        beat()
        self.click(BUTTON_LEFT, 1)

        if demo_bounds and region is not None:
            # Ride to each edge of the active region with large clamped moves, so
            # the cursor visibly hugs the four edges of the confined screen and
            # never crosses onto another monitor.
            self._log.info("Confinement demo: riding the Mini Mon edges.")
            big = 6000
            for dx, dy in ((big, 0), (0, big), (-big, 0), (0, -big)):
                self.move_relative(dx, dy)
                beat()
                time.sleep(0.25)

        self._log.info("Self-test complete: square drawn and left click sent.")
