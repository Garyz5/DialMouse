"""Step 4 tests: keyboard back-end + shift/layer state, control surface, and the
watchdog teardown-fire guard.

Drives real OSC + raw-text datagrams through the real UdpReceiver -> EventCore ->
KeyboardController into recording mock backends, so the whole pipeline is
verified with no display and no Companion. Plus pure unit tests for the movement
mode factors and the watchdog's fire decision.

    python tests/test_step4.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pythonosc.osc_message_builder import OscMessageBuilder  # noqa: E402

from dialmouse import logsetup, protocol as P  # noqa: E402
from dialmouse.config import ConfineConfig, MiniMonConfig  # noqa: E402
from dialmouse.confine import ConfineController  # noqa: E402
from dialmouse.events import EventCore  # noqa: E402
from dialmouse.keyboard import KeyboardController  # noqa: E402
from dialmouse.monitors import Monitor  # noqa: E402
from dialmouse.movement import AXIS_X, MovementModel  # noqa: E402
from dialmouse.server import UdpReceiver  # noqa: E402
from dialmouse.watchdog import Watchdog  # noqa: E402

logsetup.setup_logging(verbose=False)


# --------------------------------------------------------------------------- #
# Recording fakes
# --------------------------------------------------------------------------- #

class MockBackend:
    def __init__(self):
        self.moves = []; self.scrolls = []; self.downs = []
        self.ups = []; self.clicks = []; self.move_tos = []

    def move_relative(self, dx, dy): self.moves.append((dx, dy))
    def scroll(self, dx, dy): self.scrolls.append((dx, dy))
    def button_down(self, name): self.downs.append(name)
    def button_up(self, name): self.ups.append(name)
    def click(self, name, count=1): self.clicks.append((name, count))
    def move_to(self, x, y): self.move_tos.append((x, y))


class FakeKey:
    """Stand-in for a pynput Key (non-str, so the controller treats it special)."""
    def __init__(self, name): self.name = name
    def __repr__(self): return f"<Key {self.name}>"
    def __eq__(self, o): return isinstance(o, FakeKey) and o.name == self.name
    def __hash__(self): return hash(self.name)


class MockKeyBackend:
    """Mirrors KeyboardBackend's resolve/tap/press/release/type_text API."""
    _SPECIALS = {
        "enter", "return", "esc", "escape", "tab", "space", "backspace",
        "delete", "del", "home", "end", "up", "down", "left", "right",
        "shift", "ctrl", "control", "alt", "option", "win", "cmd", "super", "meta",
    }
    _CANON = {"return": "enter", "escape": "esc", "del": "delete",
              "control": "ctrl", "option": "alt",
              "cmd": "win", "super": "win", "meta": "win"}

    def __init__(self):
        self.taps = []; self.presses = []; self.releases = []; self.typed = []
        for n in range(1, 13):
            self._SPECIALS.add(f"f{n}")

    def resolve(self, name):
        if not name:
            return None
        low = name.lower()
        if low in self._SPECIALS:
            return FakeKey(self._CANON.get(low, low))
        if len(name) == 1:
            return name
        return None

    def tap(self, key):
        if key is not None: self.taps.append(key)
    def press(self, key):
        if key is not None: self.presses.append(key)
    def release(self, key):
        if key is not None: self.releases.append(key)
    def type_text(self, text):
        if text: self.typed.append(text)


def _fake_monitors():
    return [Monitor(0, 0, 0, 2560, 1440, True, r"\\.\D3"),
            Monitor(1, 2560, 0, 1920, 1080, False, r"\\.\D1"),
            Monitor(2, 4480, 0, 1920, 1080, False, r"\\.\D4")]


def _make(ppt=6):
    mock = MockBackend()
    kbmock = MockKeyBackend()
    movement = MovementModel(pixels_per_tick=ppt, accel_enabled=False,
                             precision_factor=0.5, turbo_factor=3.0,
                             sensitivity_presets=[3, 6, 12])
    confine = ConfineController(
        ConfineConfig(minimon=MiniMonConfig(match="index", index=2)),
        monitor_source=_fake_monitors)
    keyboard = KeyboardController(kbmock, snippets=["Hello, world", "lower third"])
    core = EventCore(movement, mock, confine, enabled=True, keyboard=keyboard)
    rx = UdpReceiver(core, max_events_per_sec=5000)
    return rx, core, mock, kbmock, movement


def _osc(address, *args):
    b = OscMessageBuilder(address=address)
    for a in args:
        b.add_arg(a)
    return b.build().dgram


# --------------------------------------------------------------------------- #
# Keyboard — shift/layer state
# --------------------------------------------------------------------------- #

def test_letter_tap_unshifted_types_lowercase():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.KEY_TAP, "a"))
    assert kb.typed == ["a"] and kb.taps == []


def test_latched_shift_types_uppercase_letter():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.KEY_MOD_TOGGLE, "shift"))
    rx._handle_datagram(_osc(P.KEY_TAP, "a"))
    assert kb.typed == ["A"]


def test_latched_shift_maps_number_to_symbol():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.KEY_MOD_TOGGLE, "shift"))
    rx._handle_datagram(_osc(P.KEY_TAP, "1"))
    rx._handle_datagram(_osc(P.KEY_TAP, "="))
    assert kb.typed == ["!", "+"]


def test_shift_toggles_off():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.KEY_MOD_TOGGLE, "shift"))   # on
    rx._handle_datagram(_osc(P.KEY_MOD_TOGGLE, "shift"))   # off
    rx._handle_datagram(_osc(P.KEY_TAP, "a"))
    assert kb.typed == ["a"]


def test_inline_ctrl_combo_holds_physically():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.KEY_TAP, "ctrl+c"))
    # ctrl physically held around a real key tap (so the shortcut registers).
    assert kb.presses == [FakeKey("ctrl")]
    assert kb.taps == ["c"]
    assert kb.releases == [FakeKey("ctrl")]
    assert kb.typed == []   # NOT the text path


def test_shift_plus_special_holds_physically():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.KEY_TAP, "shift+tab"))
    assert kb.presses == [FakeKey("shift")]
    assert kb.taps == [FakeKey("tab")]
    assert kb.releases == [FakeKey("shift")]


def test_special_key_tap_no_shift():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.KEY_TAP, "enter"))
    assert kb.taps == [FakeKey("enter")] and kb.typed == []


def test_key_down_up_and_type_and_snippet():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.KEY_DOWN, "ctrl"))
    rx._handle_datagram(_osc(P.KEY_UP, "ctrl"))
    rx._handle_datagram(_osc(P.KEY_TYPE, "abc"))
    rx._handle_datagram(_osc(P.KEY_SNIPPET, 1))
    assert kb.presses == [FakeKey("ctrl")] and kb.releases == [FakeKey("ctrl")]
    assert kb.typed == ["abc", "Hello, world"]


def test_snippet_out_of_range_is_ignored():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.KEY_SNIPPET, 9))
    assert kb.typed == []


# --------------------------------------------------------------------------- #
# Control surface
# --------------------------------------------------------------------------- #

def test_double_click():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.CLICK_DOUBLE))
    assert mock.clicks == [("left", 2)]


def test_draglock_latches_and_releases():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.DRAGLOCK_TOGGLE))
    assert mock.downs == ["left"] and mock.ups == []
    rx._handle_datagram(_osc(P.DRAGLOCK_TOGGLE))
    assert mock.ups == ["left"]


def test_turbo_scales_movement():
    rx, core, mock, kb, _ = _make(ppt=6)
    rx._handle_datagram(_osc(P.MODE_TURBO, 1))
    rx._handle_datagram(_osc(P.MOVE_X, 1))      # 6 * 3.0 = 18
    rx._handle_datagram(_osc(P.MODE_TURBO, 0))
    rx._handle_datagram(_osc(P.MOVE_X, 1))      # back to 6
    assert mock.moves == [(18, 0), (6, 0)]


def test_sensitivity_preset_jump():
    rx, core, mock, kb, _ = _make(ppt=6)
    rx._handle_datagram(_osc(P.SENSITIVITY_PRESET, 1))   # preset[0] = 3
    rx._handle_datagram(_osc(P.MOVE_X, 1))
    rx._handle_datagram(_osc(P.SENSITIVITY_PRESET, 3))   # preset[2] = 12
    rx._handle_datagram(_osc(P.MOVE_X, 1))
    assert mock.moves == [(3, 0), (12, 0)]


def test_pause_gates_keys_but_not_mod_toggle():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.CONTROL_ENABLED, 0))      # pause
    rx._handle_datagram(_osc(P.KEY_TAP, "a"))            # ignored
    assert kb.typed == []
    rx._handle_datagram(_osc(P.KEY_MOD_TOGGLE, "shift")) # still latches state
    rx._handle_datagram(_osc(P.CONTROL_ENABLED, 1))      # resume
    rx._handle_datagram(_osc(P.KEY_TAP, "a"))            # now types, shift latched
    assert kb.typed == ["A"]


def test_pause_releases_draglock():
    rx, core, mock, kb, _ = _make()
    rx._handle_datagram(_osc(P.DRAGLOCK_TOGGLE))         # left held
    assert mock.downs == ["left"]
    rx._handle_datagram(_osc(P.CONTROL_ENABLED, 0))      # pause -> must release
    assert mock.ups == ["left"]


# --------------------------------------------------------------------------- #
# Raw-UDP text grammar (keyboard + control)
# --------------------------------------------------------------------------- #

def test_text_grammar_keyboard_and_control():
    rx, core, mock, kb, _ = _make(ppt=6)
    rx._handle_datagram(b"mod shift\nkey a\ntype hello there\ndblclick\ndraglock")
    assert kb.typed == ["A", "hello there"]
    assert mock.clicks == [("left", 2)]
    assert mock.downs == ["left"]


def test_text_grammar_modes_and_preset():
    rx, core, mock, kb, _ = _make(ppt=6)
    rx._handle_datagram(b"turbo on\ndx 1\nturbo off\npreset 1\ndx 1")
    assert mock.moves == [(18, 0), (3, 0)]


# --------------------------------------------------------------------------- #
# Movement mode factors (pure)
# --------------------------------------------------------------------------- #

def test_precision_and_turbo_factor_pure():
    m = MovementModel(pixels_per_tick=8, accel_enabled=False,
                      precision_factor=0.25, turbo_factor=2.0)
    assert m.tick_to_pixels(AXIS_X, 1, 100.0) == 8
    m.set_precision(True)
    assert m.tick_to_pixels(AXIS_X, 1, 200.0) == 2       # 8 * 0.25
    m.set_turbo(True)                                    # turbo wins over precision
    assert m.tick_to_pixels(AXIS_X, 1, 300.0) == 16      # 8 * 2.0
    m.set_turbo(False)
    assert m.tick_to_pixels(AXIS_X, 1, 400.0) == 2       # precision still on
    m.set_precision(False)
    assert m.tick_to_pixels(AXIS_X, 1, 500.0) == 8


def test_sensitivity_preset_pure():
    m = MovementModel(pixels_per_tick=6, sensitivity_presets=[3, 6, 12])
    assert m.set_sensitivity_preset(1) == 3
    assert m.set_sensitivity_preset(3) == 12
    assert m.set_sensitivity_preset(99) == 12   # out of range: unchanged


# --------------------------------------------------------------------------- #
# Watchdog teardown-fire guard (Step 3 carryover bug)
# --------------------------------------------------------------------------- #

def test_watchdog_should_fire_guard():
    fired = []
    wd = Watchdog(timeout=0.1, check_interval=0.05, on_hang=lambda e: fired.append(e))
    assert wd._should_fire(0.2) is True       # over timeout, healthy -> fire
    assert wd._should_fire(0.05) is False     # under timeout -> no
    wd.pause()
    assert wd._should_fire(0.2) is False       # paused -> no false fire
    wd.resume()
    assert wd._should_fire(0.2) is True
    wd.stop()                                  # stop() also pauses
    assert wd._should_fire(0.2) is False       # stopping -> no fire mid-teardown


def test_watchdog_paused_does_not_false_fire():
    fired = []
    wd = Watchdog(timeout=0.1, check_interval=0.03, on_hang=lambda e: fired.append(e))
    wd.start()
    wd.pause()
    time.sleep(0.25)        # well past timeout, but paused (mimics teardown)
    wd.stop()
    assert fired == [], "paused watchdog must not fire"


def test_watchdog_still_fires_when_actually_wedged():
    fired = []
    wd = Watchdog(timeout=0.1, check_interval=0.03, on_hang=lambda e: fired.append(e))
    wd.start()
    time.sleep(0.25)        # no beats, not paused -> real hang
    wd.stop()
    assert fired, "watchdog must still detect a genuine hang"


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in funcs:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(funcs)}/{len(funcs)} tests passed.")


if __name__ == "__main__":
    _run_all()
