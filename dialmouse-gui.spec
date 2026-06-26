# dialmouse-gui.spec — PyInstaller build spec for the DialMouse GUI launcher.
#
# A separate, WINDOWED (no console) one-file binary that sits at the USB root and
# launches the core binary under bin/. Its only third-party deps are pystray +
# Pillow (for the system-tray icon); if those aren't bundled it still runs and
# just minimizes normally. Build per-OS (you cannot cross-build).
#
# Build:  pyinstaller dialmouse-gui.spec

from PyInstaller.utils.hooks import collect_submodules

# pystray picks its tray backend at runtime; list them so the right one is in the
# binary on each OS (_win32 on Windows, _darwin on macOS, _xorg/_appindicator/
# _gtk on Linux). Non-existent names are harmless build-time warnings.
hiddenimports = []
for pkg in ("pystray", "PIL"):
    try:
        __import__(pkg)
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass
hiddenimports += [
    "pystray._win32", "pystray._darwin",
    "pystray._xorg", "pystray._appindicator", "pystray._gtk",
]

a = Analysis(
    ["launcher/gui.py"],
    pathex=["."],
    binaries=[],
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
    name="DialMouse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed — no black console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
