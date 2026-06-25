"""Direct HID front-end — read the Stream Deck + XL directly over USB.

The optional second front-end (Receiver/OSC is primary). When Companion is NOT
using the deck, DialMouse can read the dials itself over HID and emit the same
internal events, for standalone use. It cannot run at the same time as Companion
on the same device — HID access is exclusive.

We build on the cross-platform ``python-elgato-streamdeck`` library rather than
hand-parsing HID reports, so dial rotation/press, the touch strip, and keys are
decoded correctly for the device. The library is an **optional** dependency:
the import is guarded, and if it (or a HID backend) is missing, DialMouse still
runs in Receiver mode — only Direct HID is unavailable, with clear guidance.

Threading: the library fires callbacks from its own reader thread; our main
thread idles on a stop event and beats the watchdog. Callbacks also beat, so a
busy dial never looks like a hang and an idle deck never trips a false one.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from . import platform_info
from .hid_map import HidEventTranslator
from .logsetup import get_logger


class HidUnavailable(RuntimeError):
    """Raised when Direct HID mode can't start. Carries actionable guidance."""

    def __init__(self, message: str, guidance: str = "") -> None:
        super().__init__(message)
        self.guidance = guidance


def _hid_guidance(os_name: str) -> str:
    if os_name == platform_info.OS_LINUX:
        return (
            "Direct HID needs raw USB access to the deck:\n"
            "  * install a HID backend (hidapi) — bundled in the packaged binary;\n"
            "  * add the udev rule for Elgato devices (or run with access to the\n"
            "    device node), then re-plug the deck;\n"
            "  * make sure Companion (or Stream Deck software) isn't holding the\n"
            "    deck — HID access is exclusive.")
    if os_name == platform_info.OS_MACOS:
        return (
            "Direct HID on macOS: ensure no other app (Companion / Stream Deck) has\n"
            "  the deck open — HID access is exclusive — and grant Input Monitoring\n"
            "  if prompted.")
    if os_name == platform_info.OS_WINDOWS:
        return (
            "Direct HID on Windows: close Companion / the Elgato Stream Deck app so\n"
            "  the deck is free — HID access is exclusive — then retry.")
    return "Ensure a HID backend is present and nothing else is using the deck."


class HidFrontend:
    def __init__(
        self,
        core,
        hid_cfg,
        heartbeat: Optional[Callable[[], None]] = None,
        observe_only: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._core = core
        self._cfg = hid_cfg
        self._heartbeat = heartbeat
        self._observe = bool(observe_only)
        self._log = logger or get_logger()
        self._os = platform_info.detect_os()
        self._deck = None
        self._turn_type = None
        self._stop = threading.Event()
        self._translator = HidEventTranslator(core, hid_cfg.dials, hid_cfg.invert, self._log)

    # -- lifecycle ---------------------------------------------------------

    def open(self):
        try:
            from StreamDeck.DeviceManager import DeviceManager
            from StreamDeck.Devices.StreamDeckPlus import DialEventType
        except Exception as exc:
            raise HidUnavailable(
                f"The Stream Deck library isn't available ({exc}).",
                guidance=_hid_guidance(self._os)) from exc

        self._turn_type = DialEventType.TURN
        try:
            decks = DeviceManager().enumerate()
        except Exception as exc:
            raise HidUnavailable(
                f"No HID backend / device probe failed ({exc}).",
                guidance=_hid_guidance(self._os)) from exc

        if not decks:
            raise HidUnavailable(
                "No Stream Deck found. Is it plugged in, and is Companion or the "
                "Elgato app closed? (HID access is exclusive.)",
                guidance=_hid_guidance(self._os))

        deck = decks[0]
        try:
            deck.open()
        except Exception as exc:
            raise HidUnavailable(
                f"Could not open the deck — another app may have it ({exc}).",
                guidance=_hid_guidance(self._os)) from exc

        self._deck = deck
        try:
            self._log.info("Opened %s: %d keys, %d dials, touch=%s.",
                           deck.deck_type(), deck.key_count(), deck.dial_count(), deck.is_touch())
        except Exception:
            self._log.info("Opened a Stream Deck device.")

        deck.set_dial_callback(self._on_dial)
        try:
            deck.set_key_callback(self._on_key)
            if deck.is_touch():
                deck.set_touchscreen_callback(self._on_touch)
        except Exception as exc:
            self._log.debug("Key/touch callbacks not set: %s", exc)
        return deck

    def run(self) -> None:
        """Block until stopped. Callbacks fire from the library's reader thread;
        here we just keep the process alive and beat the watchdog."""
        mode = " (observe only — not driving the cursor)" if self._observe else ""
        self._log.info("Direct HID mode running%s. Turn/press the dials. Ctrl-C to stop.", mode)
        try:
            while not self._stop.is_set():
                self._beat()
                if not self._observe:
                    try:
                        self._core.confine_reassert()
                    except Exception:  # pragma: no cover - defensive
                        pass
                self._stop.wait(0.5)
        except KeyboardInterrupt:
            self._log.info("Interrupted; stopping HID front-end.")
        finally:
            self.close()

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        if self._deck is not None:
            try:
                self._deck.close()
            except Exception:  # pragma: no cover - defensive
                pass
            self._deck = None
            self._log.debug("Deck closed.")

    # -- callbacks (fire from the library reader thread) -------------------

    def _beat(self) -> None:
        if self._heartbeat:
            self._heartbeat()

    def _on_dial(self, deck, dial, event, value) -> None:
        self._beat()
        is_turn = (event == self._turn_type)
        if self._observe:
            self._log.info("DIAL %d  %s  %r", dial, "TURN" if is_turn else "PUSH", value)
            return
        try:
            self._translator.on_dial(dial, is_turn, value)
        except Exception as exc:  # never let a bad event kill the reader
            self._log.debug("dial handler error: %s", exc)

    def _on_key(self, deck, key, pressed) -> None:
        self._beat()
        if self._observe:
            self._log.info("KEY %d  %s", key, "down" if pressed else "up")
        else:
            try:
                self._translator.on_key(key, pressed)
            except Exception as exc:
                self._log.debug("key handler error: %s", exc)

    def _on_touch(self, deck, event, value) -> None:
        self._beat()
        if self._observe:
            self._log.info("TOUCH %s  %r", getattr(event, "name", event), value)
        else:
            try:
                self._translator.on_touch(event, value)
            except Exception as exc:
                self._log.debug("touch handler error: %s", exc)
