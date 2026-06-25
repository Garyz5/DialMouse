"""OS-level cursor clipping — confine the cursor even for MANUAL mouse movement.

The Step 2 confinement engine clamps DialMouse-driven motion: every
``move_relative`` re-clamps to the Mini Mon. But when the *user* moves a physical
mouse, the OS moves the cursor and DialMouse never sees it, so the cursor could
slide off the Mini Mon. To truly confine it we ask the OS to constrain the
cursor to a rectangle.

  * **Windows:** ``user32.ClipCursor(RECT)`` — the same mechanism games use.
    Fully reversible (``ClipCursor(NULL)`` frees it) and the OS auto-releases the
    clip when the process exits, so a crash or watchdog kill can never leave the
    cursor trapped. Windows also drops the clip on some focus/desktop changes, so
    the caller re-asserts it periodically (cheap).
  * **macOS / Linux:** not yet implemented here (documented). Confinement there
    still clamps DialMouse-driven motion via the movement clamp; manual-mouse
    clipping is a future per-OS addition (Quartz / XFixes pointer barriers).

No retained state beyond the active rectangle, so it cannot leak.
"""

from __future__ import annotations

import logging
from typing import Optional

from . import platform_info
from .logsetup import get_logger
from .virtual_desktop import Bounds


class CursorClipper:
    """Base clipper: a safe no-op that records intent and warns once."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._log = logger or get_logger()
        self._active: Optional[Bounds] = None
        self._warned = False

    @property
    def active(self) -> bool:
        return self._active is not None

    def clip(self, bounds: Bounds) -> bool:
        self._active = bounds
        if not self._warned:
            self._log.info(
                "OS-level cursor clipping isn't implemented on this OS yet; "
                "confinement clamps DialMouse motion only (a manual mouse can still roam).")
            self._warned = True
        return False

    def reassert(self) -> None:
        """Re-apply the active clip (Windows can drop it on focus changes)."""
        if self._active is not None:
            self.clip(self._active)

    def release(self) -> None:
        self._active = None


class WindowsCursorClipper(CursorClipper):
    """Confine the cursor to a rectangle via user32.ClipCursor."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        super().__init__(logger)
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        self._RECT = wintypes.RECT
        self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    def clip(self, bounds: Bounds) -> bool:
        try:
            # Bounds max is exclusive, which is exactly what ClipCursor's RECT
            # right/bottom expect (the cursor can reach max-1).
            rect = self._RECT(int(bounds.min_x), int(bounds.min_y),
                              int(bounds.max_x), int(bounds.max_y))
            ok = bool(self._user32.ClipCursor(self._ctypes.byref(rect)))
            self._active = bounds
            if not ok:
                self._log.debug("ClipCursor returned 0; will retry on next assert.")
            return ok
        except Exception as exc:
            self._log.warning("ClipCursor failed (%s); manual-mouse confinement is off.", exc)
            self._active = bounds  # remember intent so reassert can retry
            return False

    def release(self) -> None:
        try:
            self._user32.ClipCursor(None)   # NULL frees the cursor
            self._log.debug("Cursor clip released.")
        except Exception as exc:
            self._log.debug("ClipCursor(NULL) failed: %s", exc)
        self._active = None


def make_clipper(
    logger: Optional[logging.Logger] = None,
    os_name: Optional[str] = None,
) -> CursorClipper:
    os_name = os_name or platform_info.detect_os()
    if os_name == platform_info.OS_WINDOWS:
        return WindowsCursorClipper(logger)
    return CursorClipper(logger)
