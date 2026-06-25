"""Step 6 tests: the Direct HID dial-map translator and hid config parsing.

No Stream Deck is needed: the translator is fed synthetic (dial, is_turn, value)
events and we assert the exact EventCore calls. The real USB reading lives in
hid_frontend.py and is verified on hardware with --hid-test.

    python tests/test_step6.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dialmouse import logsetup  # noqa: E402
from dialmouse.config import HidConfig, _parse, default_config_dict  # noqa: E402
from dialmouse.hid_map import HidEventTranslator  # noqa: E402

logsetup.setup_logging(verbose=False)


class MockCore:
    def __init__(self):
        self.calls = []
    def move(self, axis, ticks): self.calls.append(("move", axis, ticks))
    def scroll(self, ticks): self.calls.append(("scroll", ticks))
    def button(self, name, down): self.calls.append(("button", name, down))
    def adjust_sensitivity(self, d): self.calls.append(("sens", d))
    def adjust_scroll_speed(self, d): self.calls.append(("scrollspeed", d))
    def toggle_enabled(self): self.calls.append(("pause",))
    def reset_sensitivity(self): self.calls.append(("sens_reset",))
    def toggle_scroll_invert(self): self.calls.append(("scroll_invert",))
    def draglock_toggle(self): self.calls.append(("draglock",))


def _translator(invert=None):
    core = MockCore()
    t = HidEventTranslator(core, HidConfig().dials, invert or [False] * 6)
    return t, core


# --- default dial map (turns) ----------------------------------------------

def test_default_turns():
    t, core = _translator()
    t.on_dial(0, True, 3)     # dial 1 -> Mouse Y
    t.on_dial(1, True, -2)    # dial 2 -> Mouse X
    t.on_dial(2, True, 1)     # dial 3 -> scroll
    t.on_dial(3, True, 1)     # dial 4 -> sensitivity
    t.on_dial(4, True, -1)    # dial 5 -> scroll speed
    t.on_dial(5, True, 5)     # dial 6 -> none
    assert core.calls == [
        ("move", "y", 3), ("move", "x", -2), ("scroll", 1),
        ("sens", 1), ("scrollspeed", -1),
    ]


def test_default_presses():
    t, core = _translator()
    t.on_dial(0, False, True)    # left down
    t.on_dial(0, False, False)   # left up
    t.on_dial(1, False, True)    # right down
    t.on_dial(2, False, True)    # middle down
    t.on_dial(3, False, True)    # sensitivity reset (one-shot)
    t.on_dial(3, False, False)   # release -> nothing
    t.on_dial(4, False, True)    # scroll invert
    t.on_dial(5, False, True)    # pause toggle
    assert core.calls == [
        ("button", "left", True), ("button", "left", False),
        ("button", "right", True), ("button", "middle", True),
        ("sens_reset",), ("scroll_invert",), ("pause",),
    ]


def test_invert_flips_turn_direction():
    t, core = _translator(invert=[True, False, False, False, False, False])
    t.on_dial(0, True, 3)        # inverted -> -3
    assert core.calls == [("move", "y", -3)]


def test_zero_tick_and_out_of_range_ignored():
    t, core = _translator()
    t.on_dial(0, True, 0)        # no motion
    t.on_dial(9, True, 1)        # no such dial
    t.on_dial(-1, False, True)   # negative index
    assert core.calls == []


def test_keys_and_touch_do_not_inject():
    t, core = _translator()
    t.on_key(7, True)
    t.on_key(7, False)
    t.on_touch(object(), (10, 20))
    assert core.calls == []      # unbound by default


# --- config parsing --------------------------------------------------------

def test_default_config_has_spec_dial_map():
    cfg = _parse(default_config_dict())
    assert len(cfg.hid.dials) == 6
    assert cfg.hid.dials[0] == {"turn": "move_y", "press": "button_left"}
    assert cfg.hid.dials[5] == {"turn": "none", "press": "pause_toggle"}
    assert cfg.hid.invert == [False] * 6


def test_config_validates_unknown_actions():
    raw = default_config_dict()
    raw["hid"]["dials"] = [{"turn": "bogus", "press": "button_left"},
                           {"turn": "move_x", "press": "nope"}]
    cfg = _parse(raw)
    assert cfg.hid.dials[0] == {"turn": "none", "press": "button_left"}   # bad turn -> none
    assert cfg.hid.dials[1] == {"turn": "move_x", "press": "none"}        # bad press -> none


def test_config_custom_remap_and_invert():
    raw = default_config_dict()
    raw["hid"]["dials"] = [{"turn": "scroll", "press": "draglock"}]
    raw["hid"]["invert"] = [True]
    cfg = _parse(raw)
    t = HidEventTranslator(MockCore(), cfg.hid.dials, cfg.hid.invert)
    core = t._core
    t.on_dial(0, True, 2)        # scroll, inverted -> -2
    t.on_dial(0, False, True)    # draglock
    assert core.calls == [("scroll", -2), ("draglock",)]


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in funcs:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(funcs)}/{len(funcs)} tests passed.")


if __name__ == "__main__":
    _run_all()
