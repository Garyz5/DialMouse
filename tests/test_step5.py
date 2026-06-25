"""Step 5 tests: display control (picker state machine + per-OS backend) and the
OSC return channel.

No real displays are touched: a recording mock backend stands in for the OS
operations, a fake socket captures return-channel datagrams, and the Windows
backend's command construction is checked with subprocess.run monkeypatched.

    python tests/test_step5.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pythonosc.osc_message import OscMessage  # noqa: E402
from pythonosc.osc_message_builder import OscMessageBuilder  # noqa: E402

import dialmouse.display_backend as DB  # noqa: E402
from dialmouse import logsetup, protocol as P  # noqa: E402
from dialmouse.config import ConfineConfig, MiniMonConfig  # noqa: E402
from dialmouse.confine import ConfineController  # noqa: E402
from dialmouse.display import DisplayController  # noqa: E402
from dialmouse.display_backend import WindowsDisplayBackend, make_display_backend  # noqa: E402
from dialmouse.events import EventCore  # noqa: E402
from dialmouse.feedback import FeedbackSender  # noqa: E402
from dialmouse.keyboard import KeyboardController  # noqa: E402
from dialmouse.monitors import Monitor  # noqa: E402
from dialmouse.movement import MovementModel  # noqa: E402
from dialmouse.server import UdpReceiver  # noqa: E402

logsetup.setup_logging(verbose=False)


def _fake_monitors():
    return [Monitor(0, 0, 0, 2560, 1440, True, r"\\.\D3"),
            Monitor(1, 2560, 0, 1920, 1080, False, r"\\.\D1"),
            Monitor(2, 4480, 0, 1920, 1080, False, r"\\.\D4")]   # index 2 = Mini Mon


class MockDisplayBackend:
    def __init__(self):
        self.calls = []
    def extend(self): self.calls.append(("extend",)); return True
    def duplicate_all(self): self.calls.append(("duplicate",)); return True
    def panic(self): self.calls.append(("panic",)); return True
    def mirror_pick(self, target, minimon):
        self.calls.append(("mirror", target.index, minimon.index if minimon else None)); return True
    def run_raw(self, cmd, what="preset"): self.calls.append(("raw", cmd)); return True


class FakeSock:
    def __init__(self): self.sent = []
    def sendto(self, data, addr): self.sent.append((OscMessage(data).address,
                                                     list(OscMessage(data).params)))
    def close(self): pass


def _confine():
    return ConfineController(
        ConfineConfig(minimon=MiniMonConfig(match="index", index=2)),
        monitor_source=_fake_monitors)


def _controller():
    backend = MockDisplayBackend()
    confine = _confine()
    disp = DisplayController(backend, monitor_source=_fake_monitors, confine=confine,
                             presets={"showtime": "echo hi"})
    return disp, backend, confine


# --------------------------------------------------------------------------- #
# Picker state machine
# --------------------------------------------------------------------------- #

def test_pick_ignored_when_not_armed():
    disp, backend, _ = _controller()
    assert disp.pick(1) is False
    assert backend.calls == []          # nothing switched


def test_arm_then_pick_mirrors_and_disarms():
    disp, backend, _ = _controller()
    assert disp.arm() is True
    assert disp.armed is True
    ok = disp.pick(1)
    assert ok is True
    assert backend.calls == [("mirror", 1, 2)]   # target #1 -> Mini Mon #2
    assert disp.armed is False                   # auto-disarmed after pick


def test_pick_minimon_itself_is_noop():
    disp, backend, _ = _controller()
    disp.arm()
    assert disp.pick(2) is False        # #2 IS the Mini Mon
    assert backend.calls == []


def test_pick_invalid_index():
    disp, backend, _ = _controller()
    disp.arm()
    assert disp.pick(9) is False
    assert backend.calls == [] and disp.armed is False


def test_extend_duplicate_panic_preset():
    disp, backend, _ = _controller()
    disp.arm()
    disp.extend()
    assert disp.armed is False          # extend disarms the picker
    disp.duplicate()
    disp.panic()
    assert disp.preset("showtime") is True
    assert disp.preset("nope") is False
    assert backend.calls == [("extend",), ("duplicate",), ("panic",), ("raw", "echo hi")]


def test_display_count():
    disp, _, _ = _controller()
    assert disp.display_count() == 3


# --------------------------------------------------------------------------- #
# Windows backend: dry-run + command construction
# --------------------------------------------------------------------------- #

def test_windows_dry_run_does_not_execute():
    called = []
    orig = DB.subprocess.run
    DB.subprocess.run = lambda *a, **k: called.append(a) or (_ for _ in ()).throw(AssertionError("ran!"))
    try:
        b = WindowsDisplayBackend(dry_run=True)
        assert b.extend() is True          # dry-run returns True...
        assert called == []                # ...without executing anything
    finally:
        DB.subprocess.run = orig


def test_windows_extend_uses_displayswitch_3():
    captured = {}
    class _Res:
        returncode = 0; stderr = ""
    def fake_run(cmd, **k):
        captured["cmd"] = cmd
        return _Res()
    orig = DB.subprocess.run
    DB.subprocess.run = fake_run
    try:
        b = WindowsDisplayBackend(dry_run=False)
        assert b.extend() is True
        assert captured["cmd"] == ["DisplaySwitch.exe", "3"]
    finally:
        DB.subprocess.run = orig


def test_mirror_pick_noop_without_command():
    # Safety: with no configured mirror_command, mirror-pick must do nothing.
    b = make_display_backend(dry_run=False, mirror_command="", os_name="windows")
    m = _fake_monitors()
    assert b.mirror_pick(m[1], m[2]) is False


def test_mirror_pick_uses_template_in_dry_run():
    captured = {}
    orig = DB.subprocess.run
    DB.subprocess.run = lambda *a, **k: captured.update(ran=True)
    try:
        b = make_display_backend(dry_run=True, os_name="windows",
                                 mirror_command="tool /clone {target} {minimon}")
        m = _fake_monitors()
        assert b.mirror_pick(m[1], m[2]) is True   # dry-run -> True
        assert "ran" not in captured               # but not executed
    finally:
        DB.subprocess.run = orig


# --------------------------------------------------------------------------- #
# Return-channel feedback
# --------------------------------------------------------------------------- #

def test_feedback_sends_when_enabled():
    fb = FeedbackSender(enabled=True)
    fb._sock = FakeSock()
    fb.confine_state(True)
    fb.display_armed(True)
    fb.display_count(3)
    fb.shift_state(True)
    addrs = [a for a, _ in fb._sock.sent]
    assert P.FB_CONFINE_STATE in addrs
    assert P.FB_DISPLAY_ARMED in addrs
    assert (P.FB_DISPLAY_COUNT, [3]) == fb._sock.sent[2]
    assert P.FB_KEY_SHIFT_STATE in addrs


def test_feedback_dedupes_repeats():
    fb = FeedbackSender(enabled=True)
    fb._sock = FakeSock()
    fb.confine_state(True)
    fb.confine_state(True)      # identical -> suppressed
    fb.confine_state(False)     # change -> sent
    assert len(fb._sock.sent) == 2


def test_feedback_disabled_sends_nothing():
    fb = FeedbackSender(enabled=False)
    fb._sock = FakeSock()
    fb.confine_state(True)
    fb.display_count(5)
    assert fb._sock.sent == []


# --------------------------------------------------------------------------- #
# OSC wiring: receiver -> core -> display controller / feedback
# --------------------------------------------------------------------------- #

class _NoopMouse:
    def move_relative(self, dx, dy): pass
    def scroll(self, dx, dy): pass
    def button_down(self, n): pass
    def button_up(self, n): pass
    def click(self, n, c=1): pass
    def move_to(self, x, y): pass


class _NoopKeyBackend:
    def resolve(self, name): return name if name else None
    def tap(self, k): pass
    def press(self, k): pass
    def release(self, k): pass
    def type_text(self, t): pass


def _full_core():
    mouse = _NoopMouse()
    confine = _confine()
    backend = MockDisplayBackend()
    disp = DisplayController(backend, monitor_source=_fake_monitors, confine=confine)
    kb = KeyboardController(_NoopKeyBackend())
    fb = FeedbackSender(enabled=True)
    fb._sock = FakeSock()
    movement = MovementModel(pixels_per_tick=6, accel_enabled=False)
    core = EventCore(movement, mouse, confine, enabled=True, keyboard=kb,
                     display=disp, feedback=fb)
    rx = UdpReceiver(core, max_events_per_sec=5000)
    return rx, core, backend, fb


def _osc(address, *args):
    b = OscMessageBuilder(address=address)
    for a in args:
        b.add_arg(a)
    return b.build().dgram


def test_osc_display_arm_pick_and_feedback():
    rx, core, backend, fb = _full_core()
    rx._handle_datagram(_osc(P.DISPLAY_ARM))
    assert (P.FB_DISPLAY_ARMED, [1]) in fb._sock.sent
    rx._handle_datagram(_osc(P.DISPLAY_PICK, 1))
    assert ("mirror", 1, 2) in backend.calls
    assert (P.FB_DISPLAY_ARMED, [0]) in fb._sock.sent


def test_osc_display_extend_and_panic():
    rx, core, backend, fb = _full_core()
    rx._handle_datagram(_osc(P.DISPLAY_EXTEND))
    rx._handle_datagram(_osc(P.DISPLAY_PANIC))
    assert ("extend",) in backend.calls and ("panic",) in backend.calls


def test_osc_confine_and_shift_feedback():
    rx, core, backend, fb = _full_core()
    rx._handle_datagram(_osc(P.CONFINE_TOGGLE))
    rx._handle_datagram(_osc(P.KEY_MOD_TOGGLE, "shift"))
    sent = dict(fb._sock.sent)
    assert sent.get(P.FB_CONFINE_STATE) == [1]
    assert sent.get(P.FB_KEY_SHIFT_STATE) == [1]


def test_text_grammar_display():
    rx, core, backend, fb = _full_core()
    rx._handle_datagram(b"display arm\ndisplay pick 1\ndisplay panic")
    assert ("mirror", 1, 2) in backend.calls
    assert ("panic",) in backend.calls


def test_publish_state_pushes_everything():
    rx, core, backend, fb = _full_core()
    core.publish_state()
    addrs = {a for a, _ in fb._sock.sent}
    assert {P.FB_CONFINE_STATE, P.FB_DISPLAY_ARMED, P.FB_KEY_SHIFT_STATE,
            P.FB_DISPLAY_COUNT} <= addrs


def _run_all():
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for fn in funcs:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(funcs)}/{len(funcs)} tests passed.")


if __name__ == "__main__":
    _run_all()
