"""Pure-logic tests for DialMouse Step 1.

These exercise everything that does NOT require a real display: bounds clamping,
the watchdog's hang detection (via an injected handler so we never kill the test
runner), logging setup idempotency, and environment detection.

Run from the project root:
    python -m pytest -q
or without pytest:
    python tests/test_pure.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Allow running directly (python tests/test_pure.py) without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dialmouse import logsetup, platform_info  # noqa: E402
from dialmouse.virtual_desktop import Bounds, clamp_point  # noqa: E402
from dialmouse.watchdog import Watchdog  # noqa: E402


def test_clamp_no_bounds_rounds():
    assert clamp_point(10.4, 20.6, None) == (10, 21)


def test_clamp_inside():
    b = Bounds(0, 0, 1920, 1080)
    assert clamp_point(100, 200, b) == (100, 200)


def test_clamp_low_edge():
    b = Bounds(0, 0, 1920, 1080)
    assert clamp_point(-50, -50, b) == (0, 0)


def test_clamp_high_edge_exclusive_max():
    b = Bounds(0, 0, 1920, 1080)
    # max is exclusive, so the last valid pixel is max-1.
    assert clamp_point(5000, 5000, b) == (1919, 1079)


def test_clamp_negative_origin_multimonitor():
    # A second monitor to the left gives a negative min_x.
    b = Bounds(-1920, 0, 1920, 1080)
    assert clamp_point(-3000, 500, b) == (-1920, 500)
    assert clamp_point(0, 500, b) == (0, 500)


def test_bounds_rejects_degenerate():
    failed = False
    try:
        Bounds(0, 0, 0, 100)
    except ValueError:
        failed = True
    assert failed, "degenerate bounds should raise"


def test_watchdog_detects_hang_without_killing():
    fired = {"elapsed": None}

    def on_hang(elapsed):
        fired["elapsed"] = elapsed  # record instead of os._exit

    wd = Watchdog(timeout=0.2, check_interval=0.05, on_hang=on_hang)
    wd.start()
    # Do NOT beat; the main "loop" is wedged.
    time.sleep(0.6)
    wd.stop()
    assert fired["elapsed"] is not None, "watchdog should have detected the hang"
    assert fired["elapsed"] >= 0.2


def test_watchdog_healthy_does_not_fire():
    fired = {"hit": False}

    def on_hang(_elapsed):
        fired["hit"] = True

    wd = Watchdog(timeout=0.3, check_interval=0.05, on_hang=on_hang)
    wd.start()
    # Beat steadily for ~0.6s; should never be flagged.
    end = time.monotonic() + 0.6
    while time.monotonic() < end:
        wd.beat()
        time.sleep(0.05)
    wd.stop()
    assert fired["hit"] is False, "healthy loop must not trip the watchdog"


def test_watchdog_pause_suspends_detection():
    fired = {"hit": False}

    def on_hang(_elapsed):
        fired["hit"] = True

    wd = Watchdog(timeout=0.2, check_interval=0.05, on_hang=on_hang)
    wd.start()
    with wd.paused():
        time.sleep(0.5)  # would trip if not paused
    wd.stop()
    assert fired["hit"] is False, "paused watchdog must not fire"


def test_logging_setup_is_idempotent():
    log1 = logsetup.setup_logging(verbose=True)
    n1 = len(log1.handlers)
    log2 = logsetup.setup_logging(verbose=False)
    n2 = len(log2.handlers)
    # Repeated setup must not stack handlers (a real-world leak).
    assert n1 == n2 == 1


def test_environment_snapshot_has_fields():
    env = platform_info.gather_environment()
    assert env.os_name in (
        platform_info.OS_WINDOWS,
        platform_info.OS_MACOS,
        platform_info.OS_LINUX,
        platform_info.OS_UNKNOWN,
    )
    assert env.python_version
    assert isinstance(env.as_lines(), list) and env.as_lines()


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in funcs:
        fn()
        print(f"  ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(funcs)} tests passed.")


if __name__ == "__main__":
    _run_all()
