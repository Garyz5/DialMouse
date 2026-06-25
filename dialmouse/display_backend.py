"""Display back-end: change monitor topology (extend / duplicate / mirror-pick).

This is the most system-disruptive part of DialMouse — it can rearrange real
monitors mid-show — so every operation here is built to be *safe and
recoverable*:

  * **Global modes only, by default.** ``extend`` and ``duplicate_all`` map to
    the exact same OS operations Windows itself uses for Win+P, so they are
    well-tested and always reversible. ``panic`` forces extend — the known-good
    recovery if a switch ever blanks the Mini Mon.
  * **Per-monitor mirror-pick is opt-in and configurable.** True "mirror display
    N onto the Mini Mon" needs the Windows CCD API or a staged helper tool
    (NirSoft MultiMonitorTool), which is rig-specific. Rather than guess a
    destructive command, mirror-pick runs a *user-configured* command template
    and otherwise logs-and-no-ops. Nothing dangerous happens unless you stage a
    tool and set the template.
  * **Dry-run.** With ``dry_run=True`` every command is logged but NOT executed,
    so you can verify the plumbing (OSC -> controller -> exact command) without
    touching your layout.
  * **Never crashes the app.** Every external call is guarded; a failure logs a
    warning and returns False.

Cross-platform: Windows is implemented for real; macOS (``displayplacer``) and
Linux/X11 (``xrandr``) are best-effort and clearly marked unverified; Wayland has
no universal tool (documented weak spot). Selection is by ``make_display_backend``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import List, Optional

from . import platform_info
from .logsetup import get_logger
from .monitors import Monitor

_RUN_TIMEOUT_S = 8.0


class DisplayBackend:
    """Base class. Subclasses implement the per-OS specifics; this provides the
    guarded command runner, dry-run handling, and safe no-op defaults."""

    def __init__(
        self,
        dry_run: bool = False,
        mirror_command: str = "",
        helper_path: str = "",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._dry_run = bool(dry_run)
        self._mirror_command = mirror_command or ""
        self._helper_path = helper_path or ""
        self._log = logger or get_logger()

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    # -- guarded command runner -------------------------------------------

    def _run(self, cmd: List[str], what: str) -> bool:
        """Run ``cmd`` (a list, no shell). Logs the exact command; honours
        dry-run; never raises. Returns True on success."""
        printable = " ".join(cmd)
        if self._dry_run:
            self._log.info("[dry-run] would run (%s): %s", what, printable)
            return True
        self._log.info("display: %s -> %s", what, printable)
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_RUN_TIMEOUT_S,
            )
        except FileNotFoundError:
            self._log.warning("display: command not found for %s: %s", what, cmd[0])
            return False
        except subprocess.TimeoutExpired:
            self._log.warning("display: %s timed out after %.0fs.", what, _RUN_TIMEOUT_S)
            return False
        except Exception as exc:  # pragma: no cover - defensive
            self._log.warning("display: %s failed (%s).", what, exc)
            return False
        if res.returncode != 0:
            self._log.warning("display: %s exited %d. stderr: %s",
                              what, res.returncode, (res.stderr or "").strip()[:200])
            return False
        return True

    # -- operations (overridden per-OS; base = safe no-ops) ----------------

    def run_raw(self, cmd_str: str, what: str = "preset") -> bool:
        """Run a whitespace-split command string (used by config presets).
        Honours dry-run and the guarded runner like every other operation."""
        if not cmd_str:
            return False
        return self._run(cmd_str.split(), what)

    def extend(self) -> bool:
        self._log.warning("display.extend not supported on this OS; no-op.")
        return False

    def duplicate_all(self) -> bool:
        self._log.warning("display.duplicate not supported on this OS; no-op.")
        return False

    def panic(self) -> bool:
        # Recovery defaults to "extend" wherever that is implemented.
        return self.extend()

    def mirror_pick(self, target: Monitor, minimon: Optional[Monitor]) -> bool:
        """Mirror ``target`` onto the Mini Mon via a user-configured command.

        Shared across OSes because it is intentionally generic: we only run what
        the user staged + configured, so we never ship a guessed destructive
        command. Template tokens: {tool} {target} {target_name} {minimon}
        {minimon_name}.
        """
        if not self._mirror_command:
            self._log.warning(
                "display.mirror-pick is not configured. To enable it, stage a "
                "helper (e.g. MultiMonitorTool) and set display.mirror_command "
                "in config.json. (Picker plumbing works; the switch is a no-op.)")
            return False
        tool = self._helper_path
        if tool and not (shutil.which(tool) or _exists(tool)):
            self._log.warning("display: helper not found at %r; mirror-pick no-op.", tool)
            return False
        cmd_str = self._mirror_command.format(
            tool=tool,
            target=target.index, target_name=target.name or "",
            minimon=(minimon.index if minimon else ""),
            minimon_name=(minimon.name if minimon else ""),
        )
        return self._run(cmd_str.split(), f"mirror #{target.index} -> Mini Mon")


def _exists(path: str) -> bool:
    import os
    return bool(path) and os.path.exists(path)


class WindowsDisplayBackend(DisplayBackend):
    """Windows 11. Global modes via DisplaySwitch.exe numeric args (2=duplicate,
    3=extend) — confirmed on 24H2; the old /clone /extend switches went flaky on
    22H2+. Per-monitor mirror-pick uses the configurable command template."""

    def extend(self) -> bool:
        return self._run(["DisplaySwitch.exe", "3"], "extend")

    def duplicate_all(self) -> bool:
        return self._run(["DisplaySwitch.exe", "2"], "duplicate (mirror all)")


class MacDisplayBackend(DisplayBackend):
    """macOS, best-effort and UNVERIFIED. Uses displayplacer if staged; true
    per-display mirroring is via Quartz CGConfigureDisplayMirrorOfDisplay (a
    future native path)."""

    def extend(self) -> bool:
        tool = self._helper_path or "displayplacer"
        # displayplacer needs an explicit arrangement string; without one we
        # can't safely synthesize a layout, so we log guidance rather than guess.
        self._log.warning(
            "macOS extend needs a displayplacer arrangement (set display.mirror_command "
            "/ presets). Run 'displayplacer list' to capture your layout.")
        return False


class LinuxDisplayBackend(DisplayBackend):
    """Linux/X11 via xrandr (best-effort). Wayland has no universal tool."""

    def extend(self) -> bool:
        session = platform_info.detect_linux_session()
        if session == platform_info.SESSION_WAYLAND:
            self._log.warning("Wayland has no universal display-switch tool; no-op.")
            return False
        # A safe generic extend isn't expressible without knowing outputs; the
        # user supplies xrandr commands via presets / mirror_command.
        self._log.warning("Linux extend needs an xrandr command (set display presets).")
        return False

    def duplicate_all(self) -> bool:
        self._log.warning("Linux duplicate needs an xrandr --same-as command (presets).")
        return False


def make_display_backend(
    dry_run: bool = False,
    mirror_command: str = "",
    helper_path: str = "",
    logger: Optional[logging.Logger] = None,
    os_name: Optional[str] = None,
) -> DisplayBackend:
    """Construct the right backend for the current OS."""
    os_name = os_name or platform_info.detect_os()
    kwargs = dict(dry_run=dry_run, mirror_command=mirror_command,
                  helper_path=helper_path, logger=logger)
    if os_name == platform_info.OS_WINDOWS:
        return WindowsDisplayBackend(**kwargs)
    if os_name == platform_info.OS_MACOS:
        return MacDisplayBackend(**kwargs)
    if os_name == platform_info.OS_LINUX:
        return LinuxDisplayBackend(**kwargs)
    return DisplayBackend(**kwargs)
