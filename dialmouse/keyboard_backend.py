"""Keyboard back-end: inject OS-level key taps, holds, and literal text.

The keyboard counterpart to ``mouse_backend.py``. A front-end (the OSC receiver
now, the optional HID reader later) emits abstract key events; the event core's
``KeyboardController`` resolves shift/layer state and calls into exactly this
object, so injection behaves identically regardless of input source.

Key properties (mirroring the mouse back-end so the safety story is uniform):
  * Lazy, guarded initialization. The pynput keyboard Controller is created on
    first use; if it can't be created (missing macOS Accessibility permission,
    no display/uinput on Linux) we raise the same ``DialMouseInjectionError``
    the mouse back-end uses, carrying actionable per-OS guidance.
  * No retained state that can grow. The back-end holds only the controller and
    an immutable name->Key table built once. Nothing accumulates, so it cannot
    leak.
  * This object is deliberately "dumb": it injects whatever it is told. All
    shift/layer/modifier logic lives in ``keyboard.py`` so it stays pure and
    unit-testable without a display.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from .logsetup import get_logger
# Reuse the mouse back-end's error type + per-OS guidance so a missing
# permission produces ONE consistent, actionable message across input devices.
from .mouse_backend import DialMouseInjectionError, _permission_guidance
from . import platform_info


class KeyboardBackend:
    """Injects key taps, presses/releases, and literal text via pynput."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._log = logger or get_logger()
        self._os = platform_info.detect_os()
        self._controller = None       # created lazily in _ensure()
        self._specials: Dict[str, object] = {}  # name -> pynput Key, built lazily

    # -- initialization ----------------------------------------------------

    def _ensure(self):
        """Create the pynput keyboard Controller on first use, with clear errors."""
        if self._controller is not None:
            return self._controller
        try:
            from pynput.keyboard import Controller
        except Exception as exc:  # ImportError or backend import failure
            raise DialMouseInjectionError(
                f"Could not load the keyboard-injection backend (pynput): {exc}",
                guidance=_permission_guidance(self._os),
            ) from exc
        try:
            self._controller = Controller()
        except Exception as exc:
            raise DialMouseInjectionError(
                f"Keyboard injection is not available on this system: {exc}",
                guidance=_permission_guidance(self._os),
            ) from exc
        self._build_specials()
        self._log.debug("pynput keyboard Controller ready.")
        return self._controller

    def preflight(self) -> None:
        """Eagerly verify injection works; raises DialMouseInjectionError if not."""
        self._ensure()

    def _build_specials(self) -> None:
        """Map logical key names to pynput Key objects (built once, after import)."""
        from pynput.keyboard import Key
        m: Dict[str, object] = {
            "enter": Key.enter, "return": Key.enter,
            "esc": Key.esc, "escape": Key.esc,
            "tab": Key.tab, "space": Key.space, "spc": Key.space,
            "backspace": Key.backspace, "bksp": Key.backspace, "bs": Key.backspace,
            "delete": Key.delete, "del": Key.delete,
            "insert": Key.insert, "ins": Key.insert,
            "home": Key.home, "end": Key.end,
            "page_up": Key.page_up, "pgup": Key.page_up, "pageup": Key.page_up,
            "page_down": Key.page_down, "pgdn": Key.page_down, "pagedown": Key.page_down,
            "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
            "caps_lock": Key.caps_lock, "capslock": Key.caps_lock,
            "num_lock": getattr(Key, "num_lock", Key.caps_lock), "numlock": getattr(Key, "num_lock", Key.caps_lock),
            "menu": getattr(Key, "menu", Key.cmd),
            "print_screen": getattr(Key, "print_screen", Key.esc), "prtsc": getattr(Key, "print_screen", Key.esc),
            # Modifiers (also reachable as held keys for shortcuts).
            "shift": Key.shift, "ctrl": Key.ctrl, "control": Key.ctrl,
            "alt": Key.alt, "option": Key.alt,
            "win": Key.cmd, "cmd": Key.cmd, "super": Key.cmd, "meta": Key.cmd,
        }
        for n in range(1, 21):  # F1..F20
            key = getattr(Key, f"f{n}", None)
            if key is not None:
                m[f"f{n}"] = key
        self._specials = m

    # -- resolution --------------------------------------------------------

    def resolve(self, name: str):
        """Return the injectable key for ``name``.

        A recognised special name -> its pynput Key; otherwise the literal first
        character (so ``"a"`` types ``a``). Returns None for an empty/invalid
        name so callers can ignore it rather than crash.
        """
        self._ensure()
        if not name:
            return None
        key = self._specials.get(name.lower())
        if key is not None:
            return key
        # Single printable character (letter / digit / symbol) -> itself.
        if len(name) == 1:
            return name
        self._log.debug("Unknown key name %r; ignored.", name)
        return None

    # -- injection ---------------------------------------------------------

    def tap(self, key) -> None:
        ctrl = self._ensure()
        if key is None:
            return
        ctrl.press(key)
        ctrl.release(key)

    def press(self, key) -> None:
        ctrl = self._ensure()
        if key is not None:
            ctrl.press(key)

    def release(self, key) -> None:
        ctrl = self._ensure()
        if key is not None:
            ctrl.release(key)

    def type_text(self, text: str) -> None:
        ctrl = self._ensure()
        if text:
            ctrl.type(text)
