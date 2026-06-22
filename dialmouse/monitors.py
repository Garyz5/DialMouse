"""Per-monitor enumeration and Mini Mon identification.

Step 1 only gave us the union rectangle of the whole desktop. Confinement needs
the rectangle of a *single* monitor, so here we enumerate each display.

``screeninfo`` provides cross-platform enumeration (Windows/macOS/Linux). If it
can't enumerate (headless session, missing backend), we degrade gracefully to a
single synthesized monitor from the virtual-desktop bounds, or an empty list —
never a crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .config import MiniMonConfig
from .logsetup import get_logger
from .virtual_desktop import Bounds, detect_bounds


@dataclass(frozen=True)
class Monitor:
    index: int
    x: int
    y: int
    width: int
    height: int
    is_primary: bool = False
    name: str = ""

    def to_bounds(self) -> Bounds:
        return Bounds(self.x, self.y, self.x + self.width, self.y + self.height)

    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def describe(self) -> str:
        star = " *primary" if self.is_primary else ""
        nm = f" [{self.name}]" if self.name else ""
        return (f"#{self.index}: {self.width}x{self.height} "
                f"at ({self.x},{self.y}){star}{nm}")


def enumerate_monitors() -> List[Monitor]:
    """Return all monitors. Falls back to a single synthesized one if needed."""
    log = get_logger()
    try:
        from screeninfo import get_monitors  # lazy import
        raw = get_monitors()
        monitors: List[Monitor] = []
        for i, m in enumerate(raw):
            monitors.append(Monitor(
                index=i,
                x=int(m.x), y=int(m.y),
                width=int(m.width), height=int(m.height),
                is_primary=bool(getattr(m, "is_primary", False)),
                name=str(getattr(m, "name", "") or ""),
            ))
        if monitors:
            log.debug("Enumerated %d monitor(s) via screeninfo.", len(monitors))
            return monitors
    except Exception as exc:
        log.debug("screeninfo enumeration unavailable (%s); trying fallback.", exc)

    b = detect_bounds()
    if b is not None:
        log.debug("Falling back to a single monitor from virtual-desktop bounds.")
        return [Monitor(0, b.min_x, b.min_y, b.max_x - b.min_x, b.max_y - b.min_y, True, "virtual")]
    log.warning("No monitors could be enumerated.")
    return []


def pick_minimon(monitors: List[Monitor], cfg: MiniMonConfig) -> Optional[Monitor]:
    """Select the Mini Mon from ``monitors`` per the config strategy.

    Resolution-independent by design: identification uses the device name
    (preferred) or index, never the current pixel size, so the Mini Mon is found
    correctly even after you change its resolution. Falls back through
    name -> index -> resolution -> first, logging what it did.
    """
    log = get_logger()
    if not monitors:
        return None

    # Preferred: device name (stable across resolution changes).
    if cfg.match == "name" and cfg.name:
        for m in monitors:
            if m.name and m.name == cfg.name:
                return m
        log.warning("Mini Mon name %r not found; falling back to index/resolution.", cfg.name)

    if cfg.match in ("name", "index") and cfg.index is not None:
        for m in monitors:
            if m.index == cfg.index:
                return m
        if cfg.match == "index":
            log.warning("Mini Mon index %s not found; falling back to resolution.", cfg.index)

    if cfg.match == "primary":
        for m in monitors:
            if m.is_primary:
                return m
        log.warning("No primary monitor flagged; falling back to resolution.")

    for m in monitors:
        if m.width == cfg.width and m.height == cfg.height:
            return m

    log.warning(
        "Could not identify the Mini Mon (match=%s); using first monitor. "
        "Run --identify then --set-minimon N.", cfg.match,
    )
    return monitors[0]


def monitor_by_index(monitors: List[Monitor], index: int) -> Optional[Monitor]:
    """Return the monitor with the given index, or None."""
    for m in monitors:
        if m.index == index:
            return m
    return None
