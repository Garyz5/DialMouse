"""Step 3 tests: the OSC/UDP receiver and event core.

Drives real OSC datagrams through the real UdpReceiver into a recording mock
backend, so the whole pipeline is verified with no display and no Companion.

    python tests/test_step3.py
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pythonosc.osc_message_builder import OscMessageBuilder  # noqa: E402

from dialmouse import logsetup, protocol as P  # noqa: E402
from dialmouse.config import ConfineConfig, MiniMonConfig  # noqa: E402
from dialmouse.confine import ConfineController  # noqa: E402
from dialmouse.events import EventCore  # noqa: E402
from dialmouse.monitors import Monitor  # noqa: E402
from dialmouse.movement import MovementModel  # noqa: E402
from dialmouse.server import UdpReceiver  # noqa: E402

logsetup.setup_logging(verbose=False)


class MockBackend:
    """Records the calls EventCore makes, instead of moving a real cursor."""
    def __init__(self):
        self.moves = []      # (dx, dy)
        self.scrolls = []    # (dx, dy)
        self.downs = []      # name
        self.ups = []        # name
        self.clicks = []     # (name, count)
        self.move_tos = []   # (x, y)

    def move_relative(self, dx, dy): self.moves.append((dx, dy))
    def scroll(self, dx, dy): self.scrolls.append((dx, dy))
    def button_down(self, name): self.downs.append(name)
    def button_up(self, name): self.ups.append(name)
    def click(self, name, count=1): self.clicks.append((name, count))
    def move_to(self, x, y): self.move_tos.append((x, y))


def _fake_monitors():
    return [Monitor(0, 0, 0, 2560, 1440, True, r"\\.\D3"),
            Monitor(1, 2560, 0, 1920, 1080, False, r"\\.\D1"),
            Monitor(2, 4480, 0, 1920, 1080, False, r"\\.\D4")]


def _make(core_enabled=True, max_eps=5000, ppt=6):
    mock = MockBackend()
    movement = MovementModel(pixels_per_tick=ppt, accel_enabled=False)
    confine = ConfineController(
        ConfineConfig(minimon=MiniMonConfig(match="index", index=2)),
        monitor_source=_fake_monitors)
    core = EventCore(movement, mock, confine, enabled=core_enabled)
    rx = UdpReceiver(core, max_events_per_sec=max_eps)
    return rx, core, mock, confine


def _osc(address, *args):
    b = OscMessageBuilder(address=address)
    for a in args:
        b.add_arg(a)
    return b.build().dgram


# --- OSC pipeline -----------------------------------------------------------

def test_osc_move_x_to_pixels():
    rx, core, mock, _ = _make(ppt=6)
    rx._handle_datagram(_osc(P.MOVE_X, 1))
    assert mock.moves == [(6, 0)]


def test_osc_move_y_and_scroll():
    rx, core, mock, _ = _make(ppt=6)
    rx._handle_datagram(_osc(P.MOVE_Y, 1))
    rx._handle_datagram(_osc(P.SCROLL, 2))
    assert mock.moves == [(0, 6)]
    # scroll +2 means down; EventCore negates for pynput -> (0, -2) lines.
    assert mock.scrolls == [(0, -2)]


def test_osc_buttons_and_click():
    rx, core, mock, _ = _make()
    rx._handle_datagram(_osc(P.BUTTON_LEFT, 1))
    rx._handle_datagram(_osc(P.BUTTON_LEFT, 0))
    rx._handle_datagram(_osc(P.CLICK_RIGHT))
    assert mock.downs == ["left"] and mock.ups == ["left"]
    assert mock.clicks == [("right", 1)]


def test_osc_tick_clamped():
    rx, core, mock, _ = _make(ppt=6)
    rx._handle_datagram(_osc(P.MOVE_X, 999999))   # absurd flood value
    # Clamped to MAX_TICKS (127) * 6 px = 762, NOT 999999*6.
    assert mock.moves == [(762, 0)]


def test_unknown_address_ignored():
    rx, core, mock, _ = _make()
    rx._handle_datagram(_osc("/dialmouse/not/real", 5))
    rx._handle_datagram(b"\x00\x01garbage-not-osc-or-text")
    assert mock.moves == [] and mock.clicks == []


# --- pause / kill-switch ----------------------------------------------------

def test_pause_gates_pointer_but_not_control():
    rx, core, mock, _ = _make()
    rx._handle_datagram(_osc(P.CONTROL_ENABLED, 0))   # pause
    rx._handle_datagram(_osc(P.MOVE_X, 1))            # should be ignored
    rx._handle_datagram(_osc(P.BUTTON_LEFT, 1))       # ignored
    assert mock.moves == [] and mock.downs == []
    rx._handle_datagram(_osc(P.CONTROL_TOGGLE))       # resume
    rx._handle_datagram(_osc(P.MOVE_X, 1))
    assert mock.moves == [(6, 0)]


# --- confinement via OSC ----------------------------------------------------

def test_osc_confine_toggle_and_park():
    rx, core, mock, confine = _make()
    assert confine.active_region() is None
    rx._handle_datagram(_osc(P.CONFINE_TOGGLE))
    assert confine.active_region() is not None          # now confined to #2
    assert mock.move_tos, "confine should snap the cursor into the Mini Mon"
    rx._handle_datagram(_osc(P.CONFINE_OFF))
    assert confine.active_region() is None


# --- raw-UDP text fallback --------------------------------------------------

def test_text_fallback_parsing():
    rx, core, mock, _ = _make(ppt=6)
    rx._handle_datagram(b"dx 1\ndy -1\nleft down\nleft up\nclick middle\nscroll 1")
    assert (6, 0) in mock.moves and (0, -6) in mock.moves
    assert mock.downs == ["left"] and mock.ups == ["left"]
    assert mock.clicks == [("middle", 1)]
    assert mock.scrolls == [(0, -1)]


def test_text_confine_and_pause():
    rx, core, mock, confine = _make()
    rx._handle_datagram(b"confine on")
    assert confine.active_region() is not None
    rx._handle_datagram(b"pause")
    rx._handle_datagram(b"dx 1")
    assert mock.moves == []          # paused


# --- rate limiting ----------------------------------------------------------

def test_rate_limiter_drops_floods():
    rx, core, mock, _ = _make(max_eps=5)
    results = [rx._rate_ok() for _ in range(10)]
    assert results[:5] == [True] * 5
    assert results[5:] == [False] * 5     # excess dropped within the 1s window


# --- real socket loopback ---------------------------------------------------

def test_socket_loopback_end_to_end():
    import threading
    rx, core, mock, _ = _make(ppt=6)
    rx._port = 12099
    rx.open()
    t = threading.Thread(target=rx.run, daemon=True)
    t.start()
    time.sleep(0.1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(5):
        s.sendto(_osc(P.MOVE_X, 1), ("127.0.0.1", 12099))
        time.sleep(0.02)
    time.sleep(0.2)
    s.close()
    rx.stop()
    t.join(timeout=1.0)
    assert len(mock.moves) == 5, f"expected 5 moves over the socket, got {len(mock.moves)}"


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in funcs:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(funcs)}/{len(funcs)} tests passed.")


if __name__ == "__main__":
    _run_all()
