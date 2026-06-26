# dialmouse.spec — PyInstaller build spec for DialMouse.
#
# Produces ONE self-contained binary per OS (run on each OS; you cannot
# cross-build). The binary embeds Python and every runtime dependency so it runs
# on a FRESH install with NO internet and NO system Python — the core offline /
# USB requirement. For Direct HID mode it also bundles the native HIDAPI library
# (staged next to this spec by the per-OS build script) so `--hid` works offline
# with no manual DLL step.
#
# Build:  pyinstaller dialmouse.spec        (see packaging/build-*.{sh,ps1})

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# --- hidden imports ---------------------------------------------------------
# These libraries import platform back-ends / submodules dynamically, which the
# static analyser can miss. Collect them explicitly so the frozen binary has
# everything it needs on every OS.
hiddenimports = []
for pkg in ("pynput", "screeninfo", "pythonosc"):
    hiddenimports += collect_submodules(pkg)

# pynput selects its input backend at runtime and the static analyser can miss
# the platform module. pynput ships ALL backends in its package, so list them
# explicitly: each per-OS binary then reliably contains the one it needs
# (_win32 on Windows, _darwin on macOS, _xorg/_uinput on Linux). Non-existent
# names are harmless warnings at build time.
hiddenimports += [
    "pynput.keyboard._win32", "pynput.mouse._win32",
    "pynput.keyboard._darwin", "pynput.mouse._darwin",
    "pynput.keyboard._xorg", "pynput.mouse._xorg",
    "pynput.keyboard._uinput",
]

# StreamDeck + hid backend are OPTIONAL (Direct HID mode). Include them if
# installed so HID works in the binary; never fail the build if absent —
# Receiver mode needs neither.
for pkg in ("StreamDeck", "hid"):
    try:
        __import__(pkg)
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

# --- native HIDAPI library (offline Direct HID) -----------------------------
# The per-OS build script stages the right file next to this spec before
# building. If it's absent the binary still builds (HID just won't be available
# until the library is present) — Receiver mode is unaffected.
binaries = []
_hidapi_names = {
    "win32": ["hidapi.dll", "libhidapi-0.dll"],
    "darwin": ["libhidapi.dylib"],
    "linux": ["libhidapi-libusb.so", "libhidapi-hidraw.so"],
}.get(sys.platform, [])
for _name in _hidapi_names:
    if os.path.exists(_name):
        binaries.append((_name, "."))
        break

a = Analysis(
    ["packaging/entry.py"],
    pathex=["."],
    binaries=binaries,
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="dialmouse-core",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,            # DialMouse is a command-line tool
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,        # build native arch; macOS universal2 set via build script
    codesign_identity=None,
    entitlements_file=None,
)
