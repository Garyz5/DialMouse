#!/usr/bin/env bash
# build-macos.sh — build the macOS DialMouse binary and USB layout.
# Run on macOS. Produces dist/USB/DialMouse/ ready to copy onto the stick.
# Requires internet ONCE; the resulting binary is fully offline.
#
# Note on universal2: a true Apple-Silicon + Intel universal binary needs a
# universal Python and universal wheels for every dependency. That's an advanced
# setup; by default this builds for the host architecture. Build on each arch,
# or set up a universal2 toolchain, if you need both.
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

echo "== Installing build dependencies =="
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt pyinstaller streamdeck hid pystray pillow

# Native HIDAPI (offline Direct HID). Homebrew installs it as libhidapi.dylib.
if [ -z "${SKIP_HIDAPI:-}" ]; then
    for dylib in \
        /opt/homebrew/lib/libhidapi.dylib \
        /usr/local/lib/libhidapi.dylib; do
        [ -e "$dylib" ] && cp "$dylib" "./libhidapi.dylib" && echo "   staged $dylib" && break
    done
    [ -e "./libhidapi.dylib" ] || echo "   (libhidapi.dylib not found; 'brew install hidapi' to enable HID)"
fi

echo "== Building one-file binary =="
pyinstaller --clean --noconfirm dialmouse.spec
echo "== Building GUI launcher =="
pyinstaller --clean --noconfirm dialmouse-gui.spec

echo "== Assembling USB layout =="
usb="dist/USB/DialMouse"
rm -rf "$usb"
mkdir -p "$usb/bin" "$usb/tools"
cp dist/dialmouse-core "$usb/bin/dialmouse-macos"
chmod +x "$usb/bin/dialmouse-macos"
cp dist/DialMouse "$usb/DialMouse"
chmod +x "$usb/DialMouse"
cp config.example.json              "$usb/config.example.json"
cp packaging/usb/start-macos.command "$usb/start-macos.command"
chmod +x "$usb/start-macos.command"
cp README.md                        "$usb/README.md"

echo "== Done. USB layout at $usb =="
echo "   First run: right-click dialmouse-macos -> Open (unsigned), then grant"
echo "   Accessibility in System Settings -> Privacy & Security."
