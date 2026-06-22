"""Platform & environment detection.

Two jobs:
  1. Produce a clear snapshot of the runtime environment for the debug log (the
     "comprehensive debug output" requirement). On a strange machine this is the
     first thing we'll want to read.
  2. Detect facts the mouse back-end needs to give good guidance: which OS, and
     on Linux which display server (X11 vs Wayland) and whether /dev/uinput is
     usable.

Pure detection only — no input is injected here and nothing is mutated.
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from typing import Dict, Optional

OS_WINDOWS = "windows"
OS_MACOS = "macos"
OS_LINUX = "linux"
OS_UNKNOWN = "unknown"

SESSION_X11 = "x11"
SESSION_WAYLAND = "wayland"
SESSION_NONE = "none"        # no display server detected (e.g. headless/SSH)
SESSION_UNKNOWN = "unknown"


def detect_os() -> str:
    """Return one of OS_WINDOWS / OS_MACOS / OS_LINUX / OS_UNKNOWN."""
    s = sys.platform
    if s.startswith("win"):
        return OS_WINDOWS
    if s == "darwin":
        return OS_MACOS
    if s.startswith("linux"):
        return OS_LINUX
    return OS_UNKNOWN


def detect_linux_session() -> str:
    """Best-effort Linux display-server detection.

    Order of evidence: XDG_SESSION_TYPE, then WAYLAND_DISPLAY, then DISPLAY.
    """
    if detect_os() != OS_LINUX:
        return SESSION_UNKNOWN
    xdg = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if xdg in (SESSION_X11, SESSION_WAYLAND):
        return xdg
    if os.environ.get("WAYLAND_DISPLAY"):
        return SESSION_WAYLAND
    if os.environ.get("DISPLAY"):
        return SESSION_X11
    return SESSION_NONE


def uinput_writable() -> Optional[bool]:
    """Return True/False if /dev/uinput exists and is writable, else None.

    None means "not applicable / could not determine" (e.g. non-Linux).
    """
    if detect_os() != OS_LINUX:
        return None
    path = "/dev/uinput"
    if not os.path.exists(path):
        return False
    return os.access(path, os.W_OK)


@dataclass
class Environment:
    """Snapshot of the runtime environment, suitable for debug logging."""

    os_name: str
    arch: str
    python_version: str
    platform_string: str
    linux_session: str = SESSION_UNKNOWN
    uinput_writable: Optional[bool] = None
    extra: Dict[str, str] = field(default_factory=dict)

    def as_lines(self) -> list[str]:
        lines = [
            f"OS            : {self.os_name}",
            f"Architecture  : {self.arch}",
            f"Python        : {self.python_version}",
            f"Platform      : {self.platform_string}",
        ]
        if self.os_name == OS_LINUX:
            lines.append(f"Linux session : {self.linux_session}")
            lines.append(f"/dev/uinput   : "
                         f"{'writable' if self.uinput_writable else 'not writable / missing'}")
        for k, v in self.extra.items():
            lines.append(f"{k:<14}: {v}")
        return lines


def gather_environment() -> Environment:
    """Collect the current environment into an Environment snapshot."""
    os_name = detect_os()
    return Environment(
        os_name=os_name,
        arch=platform.machine() or "unknown",
        python_version=platform.python_version(),
        platform_string=platform.platform(),
        linux_session=detect_linux_session(),
        uinput_writable=uinput_writable(),
    )
