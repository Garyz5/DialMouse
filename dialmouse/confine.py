"""Confinement engine: lock the cursor to the Mini Mon, or detach to roam free.

State machine with two states:
  * CONFINED  -> the active clamp region is the Mini Mon rectangle.
  * FREE      -> the active clamp region is None (whole virtual desktop / OS).

The mouse back-end asks this controller for the current clamp region on every
move, so toggling takes effect immediately. The Mini Mon rectangle is
re-resolvable: after a display switch (Step 5) we call ``refresh()`` so the
region tracks the Mini Mon's new geometry.

Nothing here injects input; it only computes regions and the snap target. Pure
enough to unit-test without a display by injecting a monitor list.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from .config import ConfineConfig
from .logsetup import get_logger
from .monitors import Monitor, enumerate_monitors, pick_minimon
from .virtual_desktop import Bounds


class ConfineController:
    def __init__(
        self,
        cfg: ConfineConfig,
        monitor_source: Optional[Callable[[], List[Monitor]]] = None,
    ) -> None:
        self._cfg = cfg
        self._monitor_source = monitor_source or enumerate_monitors
        self._log = get_logger()
        self._minimon: Optional[Monitor] = None
        self._confined: bool = False
        self.refresh()
        if cfg.default_on:
            self.enable()

    # -- resolution --------------------------------------------------------

    def refresh(self) -> Optional[Monitor]:
        """Re-resolve which monitor is the Mini Mon (call after display changes)."""
        monitors = self._monitor_source()
        self._minimon = pick_minimon(monitors, self._cfg.minimon)
        if self._minimon:
            self._log.debug("Mini Mon resolved to %s", self._minimon.describe())
        else:
            self._log.warning("Mini Mon could not be resolved; confinement will no-op.")
        return self._minimon

    @property
    def minimon(self) -> Optional[Monitor]:
        return self._minimon

    @property
    def is_confined(self) -> bool:
        return self._confined and self._minimon is not None

    # -- state changes -----------------------------------------------------

    def enable(self) -> bool:
        # Always re-resolve so the box uses the Mini Mon's *current* geometry
        # (its rectangle changes when you switch the monitor's resolution).
        self.refresh()
        if self._minimon is None:
            self._log.warning("Cannot confine: no Mini Mon.")
            self._confined = False
            return False
        self._confined = True
        self._log.info("Cursor confined to Mini Mon (%s).", self._minimon.describe())
        return True

    def disable(self) -> None:
        self._confined = False
        self._log.info("Cursor detached (free roam).")

    def toggle(self) -> bool:
        if self.is_confined:
            self.disable()
        else:
            self.enable()
        return self.is_confined

    # -- queries for the back-end ------------------------------------------

    def active_region(self) -> Optional[Bounds]:
        """Bounds the cursor must stay inside, or None for free roam."""
        if self.is_confined and self._minimon is not None:
            return self._minimon.to_bounds()
        return None

    def park_target(self) -> Optional[Tuple[int, int]]:
        """Centre of the Mini Mon, for the Park action; None if unknown."""
        if self._minimon is not None:
            return self._minimon.center()
        return None
