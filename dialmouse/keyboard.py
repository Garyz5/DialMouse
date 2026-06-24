"""Keyboard controller — DialMouse owns the shift/layer state machine.

This is the brain that sits between the OSC receiver and the raw
``KeyboardBackend``. It exists because Companion's expression support is limited:
rather than make Companion compute "shift is on, so key 1 means !", DialMouse
holds that state itself. Companion just sends ``key/tap 1`` and ``key/mod/toggle
shift``; the shifting happens here.

Two complementary mechanisms, each fit for purpose:

  * **Latched modifiers** (the Main-page sticky ``⇧Shift`` key, and ctrl/alt/win
    if you latch them). ``mod_toggle("shift")`` flips a remembered flag. While
    shift is latched, tapping a letter/number/symbol emits the *shifted
    character as text* — we don't physically hold the Shift key down between
    taps, which avoids interfering with the user's real keyboard.

  * **Inline combos** in a tap name, e.g. ``ctrl+c`` or ``ctrl+shift+z`` (used by
    Utility-page Copy/Cut/Paste/Undo, Shift+Tab, etc.). Here the modifiers ARE
    physically held around the single tap, because that's what application
    shortcuts require. One Companion action per shortcut.

The two compose: a latched modifier is simply OR-ed into every tap's modifier
set. A tap that ends up needing ctrl/alt/win (from either source) always takes
the physical-hold path so the shortcut registers; a tap needing only shift takes
the text path.

Pure and unit-testable: inject a recording fake backend and assert the exact
press/release/type calls with no display.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Set, Tuple

from .logsetup import get_logger

# US-QWERTY shifted forms of the number row and symbol keys. Used only for the
# text path (latched/lone Shift); application shortcuts go through physical hold.
_SHIFT_SYMBOLS = {
    "1": "!", "2": "@", "3": "#", "4": "$", "5": "%",
    "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
    "-": "_", "=": "+", "[": "{", "]": "}", "\\": "|",
    ";": ":", "'": '"', ",": "<", ".": ">", "/": "?", "`": "~",
}

# Logical modifier names -> canonical internal name. Canonical names are also
# valid key names the backend understands, so we hold them by resolving the same
# string.
_MOD_CANON = {
    "shift": "shift",
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "option": "alt",
    "win": "win", "cmd": "win", "super": "win", "meta": "win",
}
_MOD_ORDER = ("ctrl", "alt", "win", "shift")  # deterministic press order


class KeyboardController:
    """Owns latched shift/modifier state and resolves taps to injection calls."""

    def __init__(
        self,
        backend,
        snippets: Optional[List[str]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._backend = backend
        self._snippets = list(snippets or [])
        self._log = logger or get_logger()
        # Latched modifiers (sticky). All off at start.
        self._latched = {"shift": False, "ctrl": False, "alt": False, "win": False}

    # -- state -------------------------------------------------------------

    @property
    def shift_latched(self) -> bool:
        return self._latched["shift"]

    def mod_toggle(self, name: str) -> Optional[bool]:
        """Flip a latched modifier. Returns the new state, or None if unknown."""
        if not name:
            return None
        canon = _MOD_CANON.get(name.lower())
        if canon is None:
            self._log.debug("mod_toggle: unknown modifier %r; ignored.", name)
            return None
        self._latched[canon] = not self._latched[canon]
        state = self._latched[canon]
        self._log.info("Modifier %s %s.", canon, "latched" if state else "released")
        return state

    # -- parsing -----------------------------------------------------------

    def _parse(self, name: str) -> Tuple[Set[str], str]:
        """Split ``ctrl+shift+c`` into ({'ctrl','shift'}, 'c').

        Only treats it as a combo when every segment is non-empty and all but the
        last are known modifiers, so a lone ``+`` (length-1) or an unknown token
        is left as a literal base name.
        """
        if "+" not in name or len(name) == 1:
            return set(), name
        parts = name.split("+")
        if any(p == "" for p in parts):
            return set(), name  # e.g. "++" or trailing + -> treat literally
        *mods, base = parts
        canon: Set[str] = set()
        for m in mods:
            c = _MOD_CANON.get(m.lower())
            if c is None:
                # Not a real modifier prefix; treat the whole thing literally.
                return set(), name
            canon.add(c)
        return canon, base

    def _effective(self, transient: Set[str]) -> Set[str]:
        latched = {m for m, on in self._latched.items() if on}
        return latched | transient

    # -- public actions ----------------------------------------------------

    def tap(self, name: str) -> None:
        """Tap ``name`` honoring latched + inline modifiers.

        Text path (only shift, no ctrl/alt/win, base is a character): emit the
        shifted character as text — no physical modifier held.
        Shortcut path (any ctrl/alt/win, or a named special key): physically hold
        the effective modifiers around a single key tap.
        """
        if not name:
            return
        transient, base = self._parse(name)
        mods = self._effective(transient)
        key = self._backend.resolve(base)
        if key is None:
            return

        is_char = isinstance(key, str)
        needs_hold = bool(mods & {"ctrl", "alt", "win"}) or not is_char

        if is_char and not needs_hold:
            ch = self._shifted_char(base) if "shift" in mods else base
            self._backend.type_text(ch)
            return

        # Physical-hold path: press mods (deterministic order), tap, release.
        held = [m for m in _MOD_ORDER if m in mods]
        for m in held:
            self._backend.press(self._backend.resolve(m))
        try:
            self._backend.tap(key)
        finally:
            for m in reversed(held):
                self._backend.release(self._backend.resolve(m))

    def key_down(self, name: str) -> None:
        """Press and hold a single resolved key (no shift/layer logic)."""
        if not name:
            return
        self._backend.press(self._backend.resolve(name))

    def key_up(self, name: str) -> None:
        """Release a single resolved key."""
        if not name:
            return
        self._backend.release(self._backend.resolve(name))

    def type_text(self, text: str) -> None:
        if text:
            self._backend.type_text(str(text))

    def snippet(self, n: int) -> None:
        """Type config-defined snippet ``n`` (1-based)."""
        idx = int(n) - 1
        if 0 <= idx < len(self._snippets):
            self._backend.type_text(self._snippets[idx])
        else:
            self._log.debug("snippet %s out of range (have %d).", n, len(self._snippets))

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _shifted_char(base: str) -> str:
        if base in _SHIFT_SYMBOLS:
            return _SHIFT_SYMBOLS[base]
        if len(base) == 1 and base.isalpha():
            return base.upper()
        return base
