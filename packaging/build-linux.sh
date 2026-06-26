#!/usr/bin/env bash
# build-linux.sh — build the Linux DialMouse binary and USB layout.
# Run on Linux (x86_64). Produces dist/USB/DialMouse/ ready to copy onto the
# stick. Requires internet ONCE; the resulting binary is fully offline.
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

echo "== Installing build dependencies =="
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt pyinstaller streamdeck hid pystray pillow

# Native HIDAPI (offline Direct HID) is optional on Linux: if the system
# libhidapi-libusb.so is present the spec bundles it; otherwise HID is simply
# unavailable in the binary and Receiver mode still works.
#   sudo apt-get install libhidapi-libusb0   # to enable HID
for so in /usr/lib/x86_64-linux-gnu/libhidapi-libusb.so* /usr/lib/libhidapi-libusb.so*; do
    [ -e "$so" ] && cp "$so" "./libhidapi-libusb.so" && echo "   staged $so" && break
done

echo "== Building one-file binary =="
pyinstaller --clean --noconfirm dialmouse.spec
echo "== Building GUI launcher =="
pyinstaller --clean --noconfirm dialmouse-gui.spec

echo "== Assembling USB layout =="
usb="dist/USB/DialMouse"
rm -rf "$usb"
mkdir -p "$usb/bin" "$usb/tools"
cp dist/dialmouse "$usb/bin/dialmouse-linux"
chmod +x "$usb/bin/dialmouse-linux"
cp dist/DialMouse "$usb/DialMouse"
chmod +x "$usb/DialMouse"
cp config.example.json             "$usb/config.example.json"
cp packaging/usb/start-linux.sh    "$usb/start-linux.sh"
chmod +x "$usb/start-linux.sh"
cp README.md                       "$usb/README.md"

echo "== Done. USB layout at $usb =="
