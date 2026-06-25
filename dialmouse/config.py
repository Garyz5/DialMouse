"""Configuration: documented defaults loaded from a JSON file beside the binary.

Principles:
  * Every option has a sensible default, so a missing or partial config.json is
    fine — we fill the gaps and log what we used.
  * Validation never crashes the app. A bad value logs a warning and falls back
    to the default for that field only.
  * Unknown keys are preserved on write but ignored on read, so future options
    and hand-edits survive round-trips.

Step 2 implements the movement / confine / network / meta sections. Keyboard and
display sections are accepted and passed through for later steps.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .logsetup import get_logger

CONFIG_FILENAME = "config.json"


# --------------------------------------------------------------------------- #
# Typed sub-sections used by Step 2.
# --------------------------------------------------------------------------- #

@dataclass
class AccelConfig:
    enabled: bool = True
    window_ms: float = 40.0
    max_factor: float = 4.0


@dataclass
class ScrollConfig:
    lines_per_tick: int = 1
    invert: bool = False


@dataclass
class MovementConfig:
    pixels_per_tick: int = 6
    invert_x: bool = False
    invert_y: bool = False
    accel: AccelConfig = field(default_factory=AccelConfig)
    scroll: ScrollConfig = field(default_factory=ScrollConfig)
    # Step 4: momentary precision (slow) / turbo (fast) hold factors, and saved
    # sensitivity presets jumped to by /dialmouse/sensitivity/preset.
    precision_factor: float = 0.25
    turbo_factor: float = 3.0
    sensitivity_presets: list = field(default_factory=lambda: [3, 6, 12])


@dataclass
class KeyboardConfig:
    # Canned text typed by /dialmouse/key/snippet N (1-based) — Utility-page
    # Snip1..3. Empty by default so nothing types unexpectedly.
    snippets: list = field(default_factory=list)


@dataclass
class FeedbackConfig:
    # OSC return channel (DialMouse -> Companion) for button lights. Off by
    # default; core input never depends on it.
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 12001


@dataclass
class DisplayConfig:
    # Step 5 display control. dry_run logs commands without running them.
    dry_run: bool = False
    helper_path: str = ""        # e.g. staged MultiMonitorTool.exe / displayplacer
    mirror_command: str = ""     # template for per-monitor mirror-pick (opt-in)
    presets: dict = field(default_factory=dict)   # name -> OS command string
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)


@dataclass
class MiniMonConfig:
    # How to identify the Mini Mon among all displays:
    #   "name"       -> by device name (e.g. "\\.\DISPLAY4"); resolution-proof,
    #                   the most stable identifier (tied to the physical output)
    #   "index"      -> use 'index' (enumeration order)
    #   "resolution" -> first monitor matching width x height
    #   "primary"    -> the primary monitor
    # Resolution of the chosen match is independent of the Mini Mon's current
    # resolution: the box is always sized from the monitor's *live* geometry.
    match: str = "resolution"
    name: Optional[str] = None
    width: int = 1920
    height: int = 1080
    index: Optional[int] = None


@dataclass
class ConfineConfig:
    default_on: bool = False
    minimon: MiniMonConfig = field(default_factory=MiniMonConfig)


@dataclass
class NetworkConfig:
    host: str = "127.0.0.1"  # localhost only; never bind the LAN.
    port: int = 12000
    max_events_per_sec: int = 5000  # flood guard; excess datagrams are dropped


@dataclass
class WatchdogConfig:
    enabled: bool = True
    timeout_s: float = 5.0


@dataclass
class Config:
    mode: str = "receiver"               # "receiver" | "hid"
    click_mode: str = "hold"             # "hold" | "tap"
    movement: MovementConfig = field(default_factory=MovementConfig)
    confine: ConfineConfig = field(default_factory=ConfineConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    keyboard: KeyboardConfig = field(default_factory=KeyboardConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)


# --------------------------------------------------------------------------- #
# Loading / validation.
# --------------------------------------------------------------------------- #

def _num(value: Any, default: float, *, lo: Optional[float] = None,
         hi: Optional[float] = None, name: str = "") -> float:
    log = get_logger()
    try:
        v = float(value)
    except (TypeError, ValueError):
        log.warning("config: %s=%r is not a number; using %r.", name, value, default)
        return default
    if lo is not None and v < lo:
        log.warning("config: %s=%r below min %r; clamping.", name, v, lo)
        v = lo
    if hi is not None and v > hi:
        log.warning("config: %s=%r above max %r; clamping.", name, v, hi)
        v = hi
    return v


def _boolean(value: Any, default: bool, name: str = "") -> bool:
    if isinstance(value, bool):
        return value
    get_logger().warning("config: %s=%r is not a bool; using %r.", name, value, default)
    return default


def _parse(raw: Dict[str, Any]) -> Config:
    cfg = Config()

    cfg.mode = raw.get("mode", cfg.mode)
    if cfg.mode not in ("receiver", "hid"):
        get_logger().warning("config: mode=%r invalid; using 'receiver'.", cfg.mode)
        cfg.mode = "receiver"

    cfg.click_mode = raw.get("click_mode", cfg.click_mode)
    if cfg.click_mode not in ("hold", "tap"):
        get_logger().warning("config: click_mode=%r invalid; using 'hold'.", cfg.click_mode)
        cfg.click_mode = "hold"

    m = raw.get("movement", {}) or {}
    cfg.movement.pixels_per_tick = int(_num(
        m.get("pixels_per_tick", 6), 6, lo=1, hi=200, name="movement.pixels_per_tick"))
    cfg.movement.invert_x = _boolean(m.get("invert_x", False), False, "movement.invert_x")
    cfg.movement.invert_y = _boolean(m.get("invert_y", False), False, "movement.invert_y")

    a = m.get("acceleration", {}) or {}
    cfg.movement.accel.enabled = _boolean(a.get("enabled", True), True, "acceleration.enabled")
    cfg.movement.accel.window_ms = _num(
        a.get("window_ms", 40), 40, lo=1, hi=2000, name="acceleration.window_ms")
    cfg.movement.accel.max_factor = _num(
        a.get("max_factor", 4.0), 4.0, lo=1.0, hi=50.0, name="acceleration.max_factor")

    s = m.get("scroll", {}) or {}
    cfg.movement.scroll.lines_per_tick = int(_num(
        s.get("lines_per_tick", 1), 1, lo=1, hi=50, name="scroll.lines_per_tick"))
    cfg.movement.scroll.invert = _boolean(s.get("invert", False), False, "scroll.invert")

    cfg.movement.precision_factor = _num(
        m.get("precision_factor", 0.25), 0.25, lo=0.01, hi=1.0, name="movement.precision_factor")
    cfg.movement.turbo_factor = _num(
        m.get("turbo_factor", 3.0), 3.0, lo=1.0, hi=20.0, name="movement.turbo_factor")
    presets = m.get("sensitivity_presets", [3, 6, 12])
    if not isinstance(presets, list) or not presets:
        if presets != [3, 6, 12]:
            get_logger().warning(
                "config: movement.sensitivity_presets=%r invalid; using [3,6,12].", presets)
        presets = [3, 6, 12]
    cfg.movement.sensitivity_presets = [
        int(_num(p, 6, lo=1, hi=200, name="movement.sensitivity_presets[]")) for p in presets]

    c = raw.get("confine", {}) or {}
    cfg.confine.default_on = _boolean(c.get("default_on", False), False, "confine.default_on")
    mm = c.get("minimon", {}) or {}
    match = mm.get("match", "resolution")
    if match not in ("name", "resolution", "index", "primary"):
        get_logger().warning("config: confine.minimon.match=%r invalid; using 'resolution'.", match)
        match = "resolution"
    cfg.confine.minimon.match = match
    name = mm.get("name", None)
    cfg.confine.minimon.name = str(name) if isinstance(name, str) and name else None
    cfg.confine.minimon.width = int(_num(mm.get("width", 1920), 1920, lo=1, name="minimon.width"))
    cfg.confine.minimon.height = int(_num(mm.get("height", 1080), 1080, lo=1, name="minimon.height"))
    idx = mm.get("index", None)
    cfg.confine.minimon.index = int(idx) if isinstance(idx, int) else None

    n = raw.get("network", {}) or {}
    host = n.get("host", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1"):
        get_logger().warning(
            "config: network.host=%r is not localhost; forcing 127.0.0.1 for safety.", host)
        host = "127.0.0.1"
    cfg.network.host = host
    cfg.network.port = int(_num(n.get("port", 12000), 12000, lo=1, hi=65535, name="network.port"))
    cfg.network.max_events_per_sec = int(_num(
        n.get("max_events_per_sec", 5000), 5000, lo=10, hi=100000, name="network.max_events_per_sec"))

    w = raw.get("watchdog", {}) or {}
    cfg.watchdog.enabled = _boolean(w.get("enabled", True), True, "watchdog.enabled")
    cfg.watchdog.timeout_s = _num(w.get("timeout_s", 5.0), 5.0, lo=0.5, hi=120, name="watchdog.timeout_s")

    kb = raw.get("keyboard", {}) or {}
    snippets = kb.get("snippets", [])
    if not isinstance(snippets, list):
        get_logger().warning("config: keyboard.snippets=%r is not a list; ignoring.", snippets)
        snippets = []
    cfg.keyboard.snippets = [str(x) for x in snippets]

    d = raw.get("display", {}) or {}
    cfg.display.dry_run = _boolean(d.get("dry_run", False), False, "display.dry_run")
    cfg.display.helper_path = str(d.get("helper_path", "") or "")
    cfg.display.mirror_command = str(d.get("mirror_command", "") or "")
    presets = d.get("presets", {})
    cfg.display.presets = {str(k): str(v) for k, v in presets.items()} if isinstance(presets, dict) else {}
    fb = d.get("feedback", {}) or {}
    cfg.display.feedback.enabled = _boolean(fb.get("enabled", False), False, "display.feedback.enabled")
    fbhost = fb.get("host", "127.0.0.1")
    if fbhost not in ("127.0.0.1", "localhost", "::1"):
        get_logger().warning(
            "config: display.feedback.host=%r is not localhost; forcing 127.0.0.1.", fbhost)
        fbhost = "127.0.0.1"
    cfg.display.feedback.host = fbhost
    cfg.display.feedback.port = int(_num(
        fb.get("port", 12001), 12001, lo=1, hi=65535, name="display.feedback.port"))
    return cfg


def default_config_dict() -> Dict[str, Any]:
    """The documented default config as a plain dict (for writing config.json)."""
    return {
        "mode": "receiver",
        "click_mode": "hold",
        "network": {"host": "127.0.0.1", "port": 12000, "max_events_per_sec": 5000},
        "movement": {
            "pixels_per_tick": 6,
            "invert_x": False,
            "invert_y": False,
            "acceleration": {"enabled": True, "window_ms": 40, "max_factor": 4.0},
            "scroll": {"lines_per_tick": 1, "invert": False},
            "precision_factor": 0.25,
            "turbo_factor": 3.0,
            "sensitivity_presets": [3, 6, 12],
        },
        "confine": {
            "default_on": False,
            "minimon": {"match": "resolution", "name": None, "width": 1920, "height": 1080, "index": None},
        },
        "watchdog": {"enabled": True, "timeout_s": 5.0},
        "keyboard": {"snippets": []},
        "display": {
            "dry_run": False,
            "helper_path": "",
            "mirror_command": "",
            "presets": {},
            "feedback": {"enabled": False, "host": "127.0.0.1", "port": 12001},
        },
    }


def load_config(path: Optional[Path]) -> Config:
    """Load config from ``path``. Missing file -> all defaults (and a note)."""
    log = get_logger()
    if path is None:
        log.debug("No config path given; using built-in defaults.")
        return Config()
    if not path.exists():
        log.info("No config at %s; using built-in defaults. "
                 "(Copy config.example.json to config.json, or run --make-config.)", path)
        return Config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("top-level JSON must be an object")
        log.debug("Loaded config from %s", path)
        return _parse(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.error("Could not read config %s (%s); using defaults.", path, exc)
        return Config()


def write_default_config(path: Path) -> None:
    """Write the documented default config.json to ``path``."""
    path.write_text(json.dumps(default_config_dict(), indent=2) + "\n", encoding="utf-8")
    get_logger().info("Wrote default config to %s", path)
