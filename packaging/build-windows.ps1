# build-windows.ps1 — build the Windows DialMouse binary and USB layout.
# Run on Windows. BUILDING needs Python 3.11+ and internet ONCE (for deps +
# hidapi.dll); the RESULTING binary is fully offline and needs no Python.
#
# Install Python from python.org first (tick "Add python.exe to PATH"). This
# script uses `py -3` / `python` via `-m PyInstaller`, so it doesn't depend on a
# `pyinstaller.exe` shim and won't be fooled by the Microsoft Store python stub.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)   # repo root

function Throw-IfFailed($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)." }
}

# --- find a REAL Python 3 interpreter (not the Store alias) -----------------
# Probe each candidate for sys.executable, then return that concrete path so all
# later calls use the interpreter directly (no launcher/alias surprises).
function Resolve-PythonExe {
    $candidates = @(
        @{ exe = "py";      args = @("-3") },
        @{ exe = "python";  args = @() },
        @{ exe = "python3"; args = @() }
    )
    foreach ($c in $candidates) {
        try {
            $probe = @($c.args) + @("-c", "import sys;print(sys.executable)")
            $exe = & $c.exe @probe 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) {
                return $exe.Trim()
            }
        } catch { }
    }
    throw @"
No working Python 3 was found on this build machine.
BUILDING the binary needs Python (only RUNNING it on the target is Python-free).
Install Python 3.11+ from https://www.python.org/downloads/ - tick
'Add python.exe to PATH' during setup - then re-run this script.
"@
}

$py = Resolve-PythonExe
Write-Host "== Using Python: $py =="
& $py --version

Write-Host "== Installing build dependencies =="
& $py -m pip install --upgrade pip;                                      Throw-IfFailed "pip upgrade"
& $py -m pip install -r requirements.txt pyinstaller streamdeck hidapi;  Throw-IfFailed "pip install"

# --- stage the native HIDAPI DLL (offline Direct HID) -----------------------
if (-not (Test-Path "hidapi.dll")) {
    Write-Host "== Fetching hidapi.dll (libusb build) =="
    $zip = "hidapi-win.zip"
    Invoke-WebRequest -Uri "https://github.com/libusb/hidapi/releases/latest/download/hidapi-win.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath "hidapi-win" -Force
    Copy-Item "hidapi-win\x64\hidapi.dll" "hidapi.dll" -Force
    Write-Host "   staged hidapi.dll"
}

# --- build (use the module, not the .exe shim) ------------------------------
Write-Host "== Building one-file binary =="
if (Test-Path "dist\dialmouse.exe") { Remove-Item "dist\dialmouse.exe" -Force }
& $py -m PyInstaller --clean --noconfirm dialmouse.spec;                 Throw-IfFailed "PyInstaller"

if (-not (Test-Path "dist\dialmouse.exe")) {
    throw "Build reported success but dist\dialmouse.exe is missing - aborting (refusing to ship a stale binary)."
}
$built = Get-Item "dist\dialmouse.exe"
Write-Host "== Built dist\dialmouse.exe ($($built.Length) bytes) =="

# --- build the GUI launcher (windowed, no console) --------------------------
Write-Host "== Building GUI launcher =="
if (Test-Path "dist\DialMouse.exe") { Remove-Item "dist\DialMouse.exe" -Force }
& $py -m PyInstaller --clean --noconfirm dialmouse-gui.spec;             Throw-IfFailed "PyInstaller (GUI)"
if (-not (Test-Path "dist\DialMouse.exe")) {
    throw "GUI build reported success but dist\DialMouse.exe is missing - aborting."
}

# --- assemble USB layout ----------------------------------------------------
Write-Host "== Assembling USB layout =="
$usb = "dist\USB\DialMouse"
Remove-Item -Recurse -Force $usb -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "$usb\bin", "$usb\tools" | Out-Null
Copy-Item "dist\dialmouse.exe"               "$usb\bin\dialmouse-win.exe" -Force
Copy-Item "dist\DialMouse.exe"               "$usb\DialMouse.exe"         -Force
Copy-Item "config.example.json"              "$usb\config.example.json"   -Force
Copy-Item "packaging\usb\start-windows.bat"  "$usb\start-windows.bat"     -Force
Copy-Item "README.md"                        "$usb\README.md"             -Force
Set-Content "$usb\tools\PUT-MultiMonitorTool-HERE.txt" `
    "Optional: drop MultiMonitorTool.exe here for per-monitor mirror-pick, then set display.helper_path + display.mirror_command in config.json."

# sanity: confirm the freshly built binary reports the expected version
Write-Host "== Verifying built binary =="
& "$usb\bin\dialmouse-win.exe" --version

Write-Host "== Done. USB layout at $usb =="
