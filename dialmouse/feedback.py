"""OSC return channel — DialMouse -> Companion feedback for button lighting.

Companion can colour/light buttons based on DialMouse state: how many displays
are connected, whether the picker is armed, whether the cursor is confined, and
whether Shift is latched. This module sends those values back over OSC/UDP.

Design rules (from the spec): **functions never depend on the lights.** Feedback
is optional (off unless ``display.feedback.enabled``), best-effort, and entirely
fire-and-forget — a send failure logs at debug level and is otherwise ignored, so
the return channel can never break the core input path. The socket is created
lazily and reused; there are no buffers, so it cannot leak.
"""

from __future__ import annotations

import logging
import socket
from typing import Optional

from . import protocol as P
from .logsetup import get_logger


class FeedbackSender:
    """Sends return-channel OSC messages to Companion. Safe no-op when disabled."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 12001,
        enabled: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._enabled = bool(enabled)
        self._log = logger or get_logger()
        self._sock: Optional[socket.socket] = None
        # Remember last-sent values so we only emit on change (avoids flooding
        # Companion with redundant updates). Fixed size; cannot grow.
        self._last = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _send(self, address: str, value: Optional[int]) -> None:
        if not self._enabled:
            return
        # De-dupe identical consecutive values per address.
        if self._last.get(address) == value:
            return
        self._last[address] = value
        try:
            from pythonosc.osc_message_builder import OscMessageBuilder
            b = OscMessageBuilder(address=address)
            if value is not None:
                b.add_arg(int(value))
            if self._sock is None:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.sendto(b.build().dgram, (self._host, self._port))
            self._log.debug("feedback -> %s %s", address, value)
        except Exception as exc:  # never let feedback break anything
            self._log.debug("feedback send failed (%s); ignored.", exc)

    # -- public state publishers ------------------------------------------

    def confine_state(self, confined: bool) -> None:
        self._send(P.FB_CONFINE_STATE, 1 if confined else 0)

    def shift_state(self, latched: bool) -> None:
        self._send(P.FB_KEY_SHIFT_STATE, 1 if latched else 0)

    def display_count(self, n: int) -> None:
        self._send(P.FB_DISPLAY_COUNT, int(n))

    def display_armed(self, armed: bool) -> None:
        self._send(P.FB_DISPLAY_ARMED, 1 if armed else 0)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
