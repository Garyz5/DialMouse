# build-windows.ps1 — build the Windows DialMouse binary and USB layout.
# Run on Windows (you cannot cross-build). Produces dist\USB\DialMouse\ ready to
# copy onto the stick. Requires internet ONCE (to fetch deps + hidapi.dll); the
# RESULTING binary is fully offline.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)   # repo root

Write-Host "== Installing build dependencies =="
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller streamdeck hidapi

# Stage the native HIDAPI DLL so Direct HID mode works offline from the binary.
if (-not (Test-Path "hidapi.dll")) {
    Write-Host "== Fetching hidapi.dll (libusb build) =="
    $zip = "hidapi-win.zip"
    Invoke-WebRequest -Uri "https://github.com/libusb/hidapi/releases/latest/download/hidapi-win.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath "hidapi-win" -Force
    Copy-Item "hidapi-win\x64\hidapi.dll" "hidapi.dll" -Force
    Write-Host "   staged hidapi.dll"
}

Write-Host "== Building one-file binary =="
pyinstaller --clean --noconfirm dialmouse.spec

Write-Host "== Assembling USB layout =="
$usb = "dist\USB\DialMouse"
Remove-Item -Recurse -Force $usb -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "$usb\bin", "$usb\tools" | Out-Null
Copy-Item "dist\dialmouse.exe"               "$usb\bin\dialmouse-win.exe" -Force
Copy-Item "config.example.json"              "$usb\config.example.json"   -Force
Copy-Item "packaging\usb\start-windows.bat"  "$usb\start-windows.bat"     -Force
Copy-Item "README.md"                        "$usb\README.md"             -Force
Set-Content "$usb\tools\PUT-MultiMonitorTool-HERE.txt" `
    "Optional: drop MultiMonitorTool.exe here for per-monitor mirror-pick, then set display.helper_path + display.mirror_command in config.json."

Write-Host "== Done. USB layout at $usb =="
