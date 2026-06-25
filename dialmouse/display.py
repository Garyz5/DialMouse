"""Display controller — the picker state machine and orchestration.

Sits between the OSC receiver and the per-OS DisplayBackend. Owns:

  * The **armed mirror-picker**: press Mirror-> (``arm``), Companion lights keys
    1..N, you tap a number (``pick``) to mirror that display onto the Mini Mon;
    arming auto-clears after a pick or an ``extend``.
  * **extend / duplicate / panic / preset** orchestration, each re-resolving the
    Mini Mon afterwards (a switch can change its geometry/role) so confinement
    keeps tracking the right screen.
  * **identify** over OSC, run as a *separate process* (``--identify``) so the
    blocking tkinter overlay never stalls the receiver loop or the watchdog.

Pure enough to unit-test without a display: inject a recording backend and a
monitor-list source. It performs no injection and emits no feedback itself — the
event core publishes return-channel state — so this object stays dependency-light.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Callable, List, Optional

from .display_backend import DisplayBackend
from .logsetup import get_logger
from .monitors import Monitor, enumerate_monitors, monitor_by_index


class DisplayController:
    def __init__(
        self,
        backend: DisplayBackend,
        monitor_source: Optional[Callable[[], List[Monitor]]] = None,
        confine=None,
        presets: Optional[dict] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._backend = backend
        self._monitors = monitor_source or enumerate_monitors
        self._confine = confine          # ConfineController, optional
        self._presets = dict(presets or {})
        self._log = logger or get_logger()
        self._armed = False

    # -- state -------------------------------------------------------------

    @property
    def armed(self) -> bool:
        return self._armed

    def display_count(self) -> int:
        try:
            return len(self._monitors())
        except Exception:
            return 0

    def _refresh_confine(self) -> None:
        # A topology change can move/resize the Mini Mon, so re-resolve it.
        if self._confine is not None:
            try:
                self._confine.refresh()
            except Exception as exc:  # pragma: no cover - defensive
                self._log.debug("confine refresh after display change skipped: %s", exc)

    # -- picker ------------------------------------------------------------

    def arm(self) -> bool:
        self._armed = True
        self._log.info("Display picker ARMED: tap a display number 1..%d to mirror "
                       "it onto the Mini Mon.", self.display_count())
        return self._armed

    def disarm(self) -> bool:
        self._armed = False
        self._log.debug("Display picker disarmed.")
        return self._armed

    def pick(self, n: int) -> bool:
        """Mirror display ``n`` onto the Mini Mon. Only acts while armed; always
        disarms afterwards."""
        if not self._armed:
            self._log.info("Display pick %s ignored (picker not armed). Press Mirror-> first.", n)
            return False
        self._armed = False
        monitors = self._monitors()
        target = monitor_by_index(monitors, int(n))
        if target is None:
            self._log.warning("Display pick: no display #%s (have %d).", n, len(monitors))
            return False
        minimon = self._confine.minimon if self._confine is not None else None
        if minimon is not None and target.index == minimon.index:
            self._log.info("Display pick #%s is the Mini Mon itself; nothing to mirror.", n)
            return False
        ok = self._backend.mirror_pick(target, minimon)
        self._refresh_confine()
        return ok

    # -- global modes ------------------------------------------------------

    def extend(self) -> bool:
        self._armed = False
        ok = self._backend.extend()
        self._refresh_confine()
        return ok

    def duplicate(self) -> bool:
        ok = self._backend.duplicate_all()
        self._refresh_confine()
        return ok

    def panic(self) -> bool:
        """Force the known-good extended layout — recovery if a switch blanks the
        Mini Mon mid-show."""
        self._armed = False
        self._log.info("Display PANIC: forcing known-good extended layout.")
        ok = self._backend.panic()
        self._refresh_confine()
        return ok

    def preset(self, name: str) -> bool:
        cmd = self._presets.get(name)
        if not cmd:
            self._log.warning("Display preset %r not defined in config.display.presets.", name)
            return False
        ok = self._backend.run_raw(cmd, f"preset {name}")
        self._refresh_confine()
        return ok

    # -- identify (separate process so it never blocks the receiver) -------

    def identify(self, seconds: float = 6.0) -> bool:
        argv = self._self_relaunch_argv(["--identify", str(seconds)])
        if argv is None:
            self._log.warning("Cannot relaunch self for identify overlay.")
            return False
        try:
            subprocess.Popen(argv, close_fds=True)
            self._log.info("Launched identify overlay in a separate process.")
            return True
        except Exception as exc:
            self._log.warning("Could not launch identify overlay: %s", exc)
            return False

    @staticmethod
    def _self_relaunch_argv(extra: List[str]) -> Optional[List[str]]:
        if getattr(sys, "frozen", False):          # packaged binary
            return [sys.executable, *extra]
        exe = sys.executable
        if not exe:
            return None
        return [exe, "-m", "dialmouse", *extra]
