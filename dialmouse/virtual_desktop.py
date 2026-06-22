"""Virtual-desktop bounds: keep the cursor on-screen.

The movement model is relative-only (etch-a-sketch), which already lets the
cursor cross multiple monitors naturally. But the spec also requires that the
cursor "can't be lost off-screen". Most OSes clamp a set-position to a valid
display area on their own, but we add an explicit clamp as a belt-and-braces
guard and so behavior is identical everywhere.

Two pieces:
  * ``clamp_point`` — a pure function (fully unit-testable, no OS calls).
  * ``detect_bounds`` — best-effort per-OS detection of the union rectangle of
    all displays. Always wrapped so a detection failure degrades to "no clamp"
    (relying on the OS) rather than crashing.

``Bounds`` is the inclusive-min / exclusive-max union rectangle of the virtual
desktop. For non-rectangular multi-monitor layouts the union may include a dead
corner; the OS still prevents the cursor from sitting in a truly invalid spot,
so clamping to the union is a safe over-approximation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from . import platform_info


@dataclass(frozen=True)
class Bounds:
    """Virtual-desktop rectangle. x in [min_x, max_x), y in [min_y, max_y)."""

    min_x: int
    min_y: int
    max_x: int
    max_y: int

    def __post_init__(self) -> None:
        if self.max_x <= self.min_x or self.max_y <= self.min_y:
            raise ValueError(f"degenerate bounds: {self}")


def clamp_point(x: float, y: float, bounds: Optional[Bounds]) -> Tuple[int, int]:
    """Clamp (x, y) into ``bounds``. If bounds is None, just round to int.

    Pure: no OS calls, no globals. The max is exclusive, so the last valid pixel
    is max-1.
    """
    xi = int(round(x))
    yi = int(round(y))
    if bounds is None:
        return xi, yi
    xi = max(bounds.min_x, min(xi, bounds.max_x - 1))
    yi = max(bounds.min_y, min(yi, bounds.max_y - 1))
    return xi, yi


# --------------------------------------------------------------------------- #
# Best-effort per-OS detection. Each path is fully guarded; any failure returns
# None and we fall back to OS-level clamping.
# --------------------------------------------------------------------------- #

def _detect_windows() -> Optional[Bounds]:
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        # SM_XVIRTUALSCREEN=76, SM_YVIRTUALSCREEN=77,
        # SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79
        x = user32.GetSystemMetrics(76)
        y = user32.GetSystemMetrics(77)
        w = user32.GetSystemMetrics(78)
        h = user32.GetSystemMetrics(79)
        if w > 0 and h > 0:
            return Bounds(x, y, x + w, y + h)
    except Exception:
        pass
    return None


def _detect_macos() -> Optional[Bounds]:
    try:
        from AppKit import NSScreen  # type: ignore

        frames = [s.frame() for s in NSScreen.screens()]
        if not frames:
            return None
        min_x = min(f.origin.x for f in frames)
        min_y = min(f.origin.y for f in frames)
        max_x = max(f.origin.x + f.size.width for f in frames)
        max_y = max(f.origin.y + f.size.height for f in frames)
        return Bounds(int(min_x), int(min_y), int(max_x), int(max_y))
    except Exception:
        pass
    return None


def _detect_linux() -> Optional[Bounds]:
    # Only meaningful under X11; under Xlib we read the default screen size.
    if platform_info.detect_linux_session() != platform_info.SESSION_X11:
        return None
    try:
        from Xlib import display as _xdisplay  # type: ignore

        d = _xdisplay.Display()
        try:
            screen = d.screen()
            w = int(screen.width_in_pixels)
            h = int(screen.height_in_pixels)
            if w > 0 and h > 0:
                return Bounds(0, 0, w, h)
        finally:
            d.close()
    except Exception:
        pass
    return None


def detect_bounds() -> Optional[Bounds]:
    """Detect the virtual-desktop bounds, or None if it can't be determined."""
    os_name = platform_info.detect_os()
    if os_name == platform_info.OS_WINDOWS:
        return _detect_windows()
    if os_name == platform_info.OS_MACOS:
        return _detect_macos()
    if os_name == platform_info.OS_LINUX:
        return _detect_linux()
    return None
