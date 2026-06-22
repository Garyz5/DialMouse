"""Step 2 pure-logic tests: movement model, confinement, config.

Run from project root:
    python tests/test_step2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dialmouse import logsetup  # noqa: E402
from dialmouse.config import Config, _parse, default_config_dict  # noqa: E402
from dialmouse.confine import ConfineController  # noqa: E402
from dialmouse.config import ConfineConfig  # noqa: E402
from dialmouse.monitors import Monitor  # noqa: E402
from dialmouse.movement import AXIS_X, AXIS_Y, MovementModel  # noqa: E402

logsetup.setup_logging(verbose=False)


# --- movement: base scaling -------------------------------------------------

def test_movement_base_scaling():
    m = MovementModel(pixels_per_tick=6, accel_enabled=False)
    # First tick has a huge gap -> no acceleration -> exactly 6 px.
    assert m.tick_to_pixels(AXIS_X, 1, now=100.0) == 6
    assert m.tick_to_pixels(AXIS_X, -1, now=200.0) == -6


def test_movement_invert():
    m = MovementModel(pixels_per_tick=6, invert_y=True, accel_enabled=False)
    assert m.tick_to_pixels(AXIS_Y, 1, now=100.0) == -6


def test_movement_no_accel_when_slow():
    m = MovementModel(pixels_per_tick=10, accel_enabled=True,
                      accel_window_ms=40, accel_max=4.0)
    m.tick_to_pixels(AXIS_X, 1, now=0.0)        # prime
    # 100 ms later (> 40 ms window) -> factor 1 -> 10 px.
    assert m.tick_to_pixels(AXIS_X, 1, now=0.100) == 10


def test_movement_full_accel_when_instant():
    m = MovementModel(pixels_per_tick=10, accel_enabled=True,
                      accel_window_ms=40, accel_max=4.0)
    m.tick_to_pixels(AXIS_X, 1, now=0.0)        # prime
    # dt ~ 0 -> factor ~ max (4.0) -> 40 px.
    assert m.tick_to_pixels(AXIS_X, 1, now=0.0) == 40


def test_movement_partial_accel():
    m = MovementModel(pixels_per_tick=10, accel_enabled=True,
                      accel_window_ms=40, accel_max=4.0)
    m.tick_to_pixels(AXIS_X, 1, now=0.0)
    # dt = 20 ms = half window -> factor = 1 + 3*(1 - 0.5) = 2.5 -> 25 px.
    assert m.tick_to_pixels(AXIS_X, 1, now=0.020) == 25


def test_movement_axes_independent():
    m = MovementModel(pixels_per_tick=10, accel_enabled=True,
                      accel_window_ms=40, accel_max=4.0)
    m.tick_to_pixels(AXIS_X, 1, now=0.0)
    # A Y tick right after should NOT inherit X's acceleration state.
    assert m.tick_to_pixels(AXIS_Y, 1, now=0.001) == 10


def test_movement_never_rounds_to_zero():
    m = MovementModel(pixels_per_tick=1, accel_enabled=False)
    assert m.tick_to_pixels(AXIS_X, 1, now=0.0) == 1


def test_scroll_and_invert():
    m = MovementModel(scroll_lines_per_tick=3, scroll_invert=False)
    assert m.scroll_to_lines(1) == 3
    assert m.scroll_to_lines(-2) == -6
    m2 = MovementModel(scroll_lines_per_tick=1, scroll_invert=True)
    assert m2.scroll_to_lines(1) == -1


def test_sensitivity_adjust_clamped():
    m = MovementModel(pixels_per_tick=6)
    assert m.adjust_sensitivity(4) == 10
    assert m.adjust_sensitivity(-100) == 1     # clamped to >=1


# --- confinement ------------------------------------------------------------

def _fake_monitors():
    # Mimics a multi-monitor rig: a big main + a 1080p Mini Mon offset to the right.
    return [
        Monitor(0, 0, 0, 3840, 1440, is_primary=True, name="main"),
        Monitor(1, 3840, 0, 1920, 1080, is_primary=False, name="minimon"),
    ]


def test_confine_resolves_minimon_by_resolution():
    cfg = ConfineConfig()  # default: match resolution 1920x1080
    c = ConfineController(cfg, monitor_source=_fake_monitors)
    assert c.minimon is not None
    assert c.minimon.index == 1


def test_confine_region_toggles():
    c = ConfineController(ConfineConfig(), monitor_source=_fake_monitors)
    assert c.active_region() is None           # starts free
    c.enable()
    region = c.active_region()
    assert region is not None
    assert (region.min_x, region.min_y, region.max_x, region.max_y) == (3840, 0, 5760, 1080)
    c.disable()
    assert c.active_region() is None


def test_confine_park_target_is_minimon_center():
    c = ConfineController(ConfineConfig(), monitor_source=_fake_monitors)
    assert c.park_target() == (3840 + 960, 540)


def test_confine_default_on():
    cfg = ConfineConfig(default_on=True)
    c = ConfineController(cfg, monitor_source=_fake_monitors)
    assert c.is_confined is True


# --- config -----------------------------------------------------------------

def test_config_defaults_roundtrip():
    cfg = _parse(default_config_dict())
    assert cfg.movement.pixels_per_tick == 6
    assert cfg.network.host == "127.0.0.1"
    assert cfg.network.port == 12000
    assert cfg.confine.minimon.width == 1920


def test_config_bad_values_fall_back():
    raw = {
        "network": {"host": "0.0.0.0", "port": 999999},   # LAN host + bad port
        "movement": {"pixels_per_tick": "lots"},          # non-numeric
    }
    cfg = _parse(raw)
    assert cfg.network.host == "127.0.0.1"     # forced to localhost
    assert cfg.network.port == 65535           # clamped
    assert cfg.movement.pixels_per_tick == 6   # fell back to default



# --- resolution-independence (the "any Mini Mon resolution" requirement) -----

from dialmouse.config import MiniMonConfig  # noqa: E402
from dialmouse.monitors import pick_minimon  # noqa: E402


def _rig_1080():
    return [Monitor(0, 0, 0, 2560, 1440, True, r"\\.\DISPLAY3"),
            Monitor(1, 2560, 1, 1920, 1080, False, r"\\.\DISPLAY1"),
            Monitor(2, 6400, 0, 1920, 1080, False, r"\\.\DISPLAY4"),
            Monitor(3, 4480, 0, 1920, 1080, False, r"\\.\DISPLAY2")]


def _rig_minimon_lowered():
    # Same rig but DISPLAY4 (the Mini Mon) dropped to 1280x720; geometry shifts.
    return [Monitor(0, 0, 0, 2560, 1440, True, r"\\.\DISPLAY3"),
            Monitor(1, 2560, 1, 1920, 1080, False, r"\\.\DISPLAY1"),
            Monitor(2, 5120, 0, 1280, 720, False, r"\\.\DISPLAY4"),
            Monitor(3, 4480, 0, 1920, 1080, False, r"\\.\DISPLAY2")]


def test_name_match_survives_resolution_change():
    cfg = MiniMonConfig(match="name", name=r"\\.\DISPLAY4", index=2)
    # At 1080p it finds DISPLAY4 with its 1920x1080 box...
    m = pick_minimon(_rig_1080(), cfg)
    assert m.name == r"\\.\DISPLAY4" and (m.width, m.height) == (1920, 1080)
    # ...and after lowering the res, the SAME name still resolves, now with the
    # new 1280x720 box and new position.
    m2 = pick_minimon(_rig_minimon_lowered(), cfg)
    assert m2.name == r"\\.\DISPLAY4" and (m2.width, m2.height) == (1280, 720)
    assert m2.to_bounds().max_x - m2.to_bounds().min_x == 1280


def test_name_match_falls_back_to_index():
    # Name not present (e.g. platform without names) -> use index.
    cfg = MiniMonConfig(match="name", name="nonexistent", index=2)
    m = pick_minimon(_rig_1080(), cfg)
    assert m.index == 2


def test_confine_uses_live_geometry_on_enable():
    # Confinement re-reads geometry when enabled, so the box matches the
    # Mini Mon's current resolution.
    state = {"rig": _rig_1080()}
    cfg = ConfineConfig(minimon=MiniMonConfig(match="name", name=r"\\.\DISPLAY4", index=2))
    c = ConfineController(cfg, monitor_source=lambda: state["rig"])
    c.enable()
    r1 = c.active_region()
    assert (r1.max_x - r1.min_x, r1.max_y - r1.min_y) == (1920, 1080)
    # User lowers the Mini Mon resolution, then toggles confine off/on.
    state["rig"] = _rig_minimon_lowered()
    c.disable()
    c.enable()
    r2 = c.active_region()
    assert (r2.max_x - r2.min_x, r2.max_y - r2.min_y) == (1280, 720)


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in funcs:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(funcs)}/{len(funcs)} tests passed.")


if __name__ == "__main__":
    _run_all()
