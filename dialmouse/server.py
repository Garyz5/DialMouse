"""UDP receiver — the Receiver-mode front-end.

Owns a single UDP socket bound to localhost and turns incoming datagrams into
EventCore calls. Handles both protocols on one port:
  * OSC (primary) — datagrams beginning with '/' or an OSC bundle.
  * raw text (fallback) — newline-delimited lines for Companion's Generic UDP
    module, e.g. "dx 1", "left down", "click right", "confine toggle".

Safety, by construction:
  * Binds to 127.0.0.1 only; additionally ignores any datagram whose source
    isn't loopback (defense in depth).
  * Processes datagrams synchronously in the recv loop — there is no queue, so
    nothing can grow without bound. If we ever can't keep up, the OS drops
    excess datagrams rather than buffering them in our process.
  * A token-style rate limit drops floods so a malicious or stuck sender can't
    peg the CPU or fling the cursor; drops are logged at most once per second.
  * All arguments are validated/coerced; unknown addresses are logged and
    ignored.
  * The recv timeout wakes the loop regularly so it always beats the watchdog
    (even when idle) and notices the shutdown flag promptly.
"""

from __future__ import annotations

import logging
import socket
import time
from typing import Callable, Dict, List, Optional

from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_message import OscMessage

from . import protocol as P
from .events import EventCore
from .logsetup import get_logger
from .movement import AXIS_X, AXIS_Y

_LOOPBACK = {"127.0.0.1", "::1"}
_MAX_DATAGRAM = 2048


def _first_int(args: List, default: Optional[int] = None) -> Optional[int]:
    if not args:
        return default
    try:
        return int(args[0])
    except (TypeError, ValueError):
        return default


def _first_str(args: List, default: str = "") -> str:
    if not args:
        return default
    return str(args[0])


class UdpReceiver:
    def __init__(
        self,
        core: EventCore,
        host: str = "127.0.0.1",
        port: int = 12000,
        heartbeat: Optional[Callable[[], None]] = None,
        max_events_per_sec: int = 5000,
        recv_timeout: float = 0.5,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._core = core
        self._host = "127.0.0.1" if host not in _LOOPBACK else host
        self._port = int(port)
        self._heartbeat = heartbeat
        self._max_eps = max(1, int(max_events_per_sec))
        self._recv_timeout = float(recv_timeout)
        self._log = logger or get_logger()
        self._sock: Optional[socket.socket] = None
        self._running = False

        # Rate-limit window state (fixed size; cannot leak).
        self._win_start = time.monotonic()
        self._win_count = 0
        self._dropped = 0

        self._dispatch: Dict[str, Callable[[List], None]] = self._build_dispatch()

    # -- dispatch table ----------------------------------------------------

    def _build_dispatch(self) -> Dict[str, Callable[[List], None]]:
        c = self._core
        return {
            P.MOVE_X: lambda a: c.move(AXIS_X, _first_int(a, 0)),
            P.MOVE_Y: lambda a: c.move(AXIS_Y, _first_int(a, 0)),
            P.SCROLL: lambda a: c.scroll(_first_int(a, 0)),
            P.BUTTON_LEFT: lambda a: c.button("left", bool(_first_int(a, 0))),
            P.BUTTON_RIGHT: lambda a: c.button("right", bool(_first_int(a, 0))),
            P.BUTTON_MIDDLE: lambda a: c.button("middle", bool(_first_int(a, 0))),
            P.CLICK_LEFT: lambda a: c.click("left"),
            P.CLICK_RIGHT: lambda a: c.click("right"),
            P.CLICK_MIDDLE: lambda a: c.click("middle"),
            P.CLICK_DOUBLE: lambda a: c.click_double(),
            P.DRAGLOCK_TOGGLE: lambda a: c.draglock_toggle(),
            P.SENSITIVITY: lambda a: c.adjust_sensitivity(_first_int(a, 0)),
            P.SENSITIVITY_PRESET: lambda a: c.sensitivity_preset(_first_int(a, 1)),
            P.SCROLLSPEED: lambda a: c.adjust_scroll_speed(_first_int(a, 0)),
            P.CONTROL_ENABLED: lambda a: c.set_enabled(bool(_first_int(a, 1))),
            P.CONTROL_TOGGLE: lambda a: c.toggle_enabled(),
            P.MODE_PRECISION: lambda a: c.set_precision(bool(_first_int(a, 0))),
            P.MODE_TURBO: lambda a: c.set_turbo(bool(_first_int(a, 0))),
            P.CONFINE_MINIMON: lambda a: c.confine_minimon(),
            P.CONFINE_OFF: lambda a: c.confine_off(),
            P.CONFINE_TOGGLE: lambda a: c.confine_toggle(),
            P.CURSOR_PARK: lambda a: c.park(),
            P.KEY_TAP: lambda a: c.key_tap(_first_str(a)),
            P.KEY_DOWN: lambda a: c.key_down(_first_str(a)),
            P.KEY_UP: lambda a: c.key_up(_first_str(a)),
            P.KEY_TYPE: lambda a: c.key_type(_first_str(a)),
            P.KEY_MOD_TOGGLE: lambda a: c.key_mod_toggle(_first_str(a)),
            P.KEY_SNIPPET: lambda a: c.key_snippet(_first_int(a, 0)),
        }

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((self._host, self._port))
        except OSError as exc:
            s.close()
            raise OSError(
                f"Could not bind {self._host}:{self._port} ({exc}). "
                f"Is another DialMouse already running, or the port in use?"
            ) from exc
        s.settimeout(self._recv_timeout)
        self._sock = s
        self._log.info("Listening for OSC/UDP on %s:%d (localhost only).",
                       self._host, self._port)

    def run(self) -> None:
        """Receive and dispatch until stop() is called. Blocking."""
        if self._sock is None:
            self.open()
        assert self._sock is not None
        self._running = True
        self._log.info("Receiver running. Pointer/scroll/buttons + confine are live.")
        while self._running:
            if self._heartbeat:
                self._heartbeat()  # beat the watchdog every loop (incl. idle).
            try:
                data, addr = self._sock.recvfrom(_MAX_DATAGRAM)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    self._log.exception("Socket error; continuing.")
                continue
            if addr[0] not in _LOOPBACK:
                self._log.warning("Ignoring datagram from non-loopback %s.", addr[0])
                continue
            if not self._rate_ok():
                continue
            self._handle_datagram(data)

    def stop(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
        self._log.debug("Receiver stopped.")

    # -- rate limiting -----------------------------------------------------

    def _rate_ok(self) -> bool:
        now = time.monotonic()
        if now - self._win_start >= 1.0:
            if self._dropped:
                self._log.warning("Rate limit: dropped %d event(s) in the last second.",
                                  self._dropped)
            self._win_start = now
            self._win_count = 0
            self._dropped = 0
        self._win_count += 1
        if self._win_count > self._max_eps:
            self._dropped += 1
            return False
        return True

    # -- parsing / dispatch ------------------------------------------------

    def _handle_datagram(self, data: bytes) -> None:
        try:
            if OscBundle.dgram_is_bundle(data):
                self._handle_bundle(OscBundle(data))
            elif data[:1] == b"/":
                msg = OscMessage(data)
                self._dispatch_address(msg.address, list(msg.params))
            else:
                self._handle_text(data)
        except Exception as exc:
            self._log.debug("Dropped malformed datagram (%s).", exc)

    def _handle_bundle(self, bundle: OscBundle) -> None:
        for i in range(bundle.num_contents):
            content = bundle.content(i)
            if isinstance(content, OscBundle):
                self._handle_bundle(content)
            else:
                self._dispatch_address(content.address, list(content.params))

    def _handle_text(self, data: bytes) -> None:
        try:
            text = data.decode("utf-8", "replace")
        except Exception:
            return
        for line in text.splitlines():
            parsed = self._parse_text_line(line.strip())
            if parsed is not None:
                self._dispatch_address(parsed[0], parsed[1])

    def _parse_text_line(self, line: str):
        """Map a raw-UDP text line to (address, args), or None to ignore."""
        if not line:
            return None
        parts = line.split()
        head = parts[0].lower()
        rest = parts[1:]

        def as_int(default=0):
            try:
                return int(rest[0])
            except (IndexError, ValueError):
                return default

        if head == "dx":
            return P.MOVE_X, [as_int()]
        if head == "dy":
            return P.MOVE_Y, [as_int()]
        if head == "scroll":
            return P.SCROLL, [as_int()]
        if head in ("left", "right", "middle") and rest:
            addr = {"left": P.BUTTON_LEFT, "right": P.BUTTON_RIGHT, "middle": P.BUTTON_MIDDLE}[head]
            return addr, [1 if rest[0].lower() == "down" else 0]
        if head == "click" and rest:
            addr = {"left": P.CLICK_LEFT, "right": P.CLICK_RIGHT, "middle": P.CLICK_MIDDLE}.get(rest[0].lower())
            return (addr, []) if addr else None
        if head == "dblclick":
            return P.CLICK_DOUBLE, []
        if head == "draglock":
            return P.DRAGLOCK_TOGGLE, []
        if head == "confine" and rest:
            opt = rest[0].lower()
            return {"on": (P.CONFINE_MINIMON, []), "off": (P.CONFINE_OFF, []),
                    "toggle": (P.CONFINE_TOGGLE, [])}.get(opt)
        if head == "park":
            return P.CURSOR_PARK, []
        if head == "pause":
            return P.CONTROL_ENABLED, [0]
        if head == "resume":
            return P.CONTROL_ENABLED, [1]
        if head == "toggle":
            return P.CONTROL_TOGGLE, []
        if head == "sensitivity":
            return P.SENSITIVITY, [as_int()]
        if head == "scrollspeed":
            return P.SCROLLSPEED, [as_int()]
        if head == "preset":
            return P.SENSITIVITY_PRESET, [as_int(1)]
        if head in ("precision", "turbo") and rest:
            on = 1 if rest[0].lower() in ("on", "1", "true") else 0
            return (P.MODE_PRECISION if head == "precision" else P.MODE_TURBO), [on]
        if head == "key" and rest:
            return P.KEY_TAP, [rest[0]]
        if head == "kdown" and rest:
            return P.KEY_DOWN, [rest[0]]
        if head == "kup" and rest:
            return P.KEY_UP, [rest[0]]
        if head == "mod" and rest:
            return P.KEY_MOD_TOGGLE, [rest[0]]
        if head == "snippet":
            return P.KEY_SNIPPET, [as_int()]
        if head == "type":
            # Everything after "type " is typed literally (preserve spacing).
            return P.KEY_TYPE, [line[len("type"):].strip()]
        return None

    def _dispatch_address(self, address: str, args: List) -> None:
        handler = self._dispatch.get(address)
        if handler is None:
            self._log.debug("Unknown/reserved address %s %r (ignored).", address, args)
            return
        self._log.debug("recv %s %r", address, args)
        handler(args)
