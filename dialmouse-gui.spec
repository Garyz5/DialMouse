# dialmouse-gui.spec — PyInstaller build spec for the DialMouse GUI launcher.
#
# A separate, WINDOWED (no console) one-file binary that sits at the USB root and
# launches the core binary under bin/. It has NO third-party dependencies — only
# the standard library (tkinter, subprocess) — so it's small and builds anywhere
# Python + Tk are present. Build per-OS (you cannot cross-build).
#
# Build:  pyinstaller dialmouse-gui.spec

a = Analysis(
    ["launcher/gui.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
