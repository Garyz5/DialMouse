"""Tests for the GUI launcher's pure (non-Tk) helpers.

    python tests/test_launcher.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launcher.gui import (  # noqa: E402
    build_command, core_binary_name, parse_extra_args, resolve_core_command,
)


def test_core_binary_name_per_os():
    assert core_binary_name("Windows") == "dialmouse-win.exe"
    assert core_binary_name("Darwin") == "dialmouse-macos"
    assert core_binary_name("Linux") == "dialmouse-linux"


def test_resolve_prefers_bin_then_root():
    base = "/usb/DialMouse"
    binpath = os.path.join(base, "bin", "dialmouse-win.exe")
    rootpath = os.path.join(base, "dialmouse-win.exe")

    # binary under bin/ wins
    cmd = resolve_core_command(base, "Windows", exists=lambda p: p == binpath)
    assert cmd == [binpath]

    # else beside the launcher
    cmd = resolve_core_command(base, "Windows", exists=lambda p: p == rootpath)
    assert cmd == [rootpath]


def test_resolve_falls_back_to_module():
    cmd = resolve_core_command("/nowhere", "Linux", exists=lambda p: False)
    assert cmd[-2:] == ["-m", "dialmouse"]   # python -m dialmouse


def test_build_command_appends_args():
    assert build_command(["dialmouse-win.exe"], ["--test"]) == ["dialmouse-win.exe", "--test"]
    assert build_command(["py", "-m", "dialmouse"], []) == ["py", "-m", "dialmouse"]


def test_parse_extra_args():
    assert parse_extra_args("") == []
    assert parse_extra_args("   ") == []
    assert parse_extra_args("--port 12000") == ["--port", "12000"]
    assert parse_extra_args("--display preset main") == ["--display", "preset", "main"]


def _run_all():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in funcs:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(funcs)}/{len(funcs)} tests passed.")


if __name__ == "__main__":
    _run_all()
