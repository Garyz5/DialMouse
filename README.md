# DialMouse

Turn the rotary dials on an Elgato Stream Deck + XL into a precise
"etch-a-sketch" mouse, plus a full input + display-control layer for a
self-contained control surface. Built to run **offline, from a USB drive, on a
fresh OS install** — no installer, no admin rights, no internet.

Two ways to drive it:

- **Receiver mode (primary):** Bitfocus Companion forwards dial/key events to
  DialMouse over localhost OSC/UDP. Companion keeps full control of the deck.
- **Direct HID mode (optional):** when Companion isn't using the deck, DialMouse
  reads the dials directly over USB. (HID access is exclusive — only one of the
  two can hold the deck at a time.)

---

## Quick start (from the USB drive)

Each OS has its own self-contained binary under `bin/`. Launch the matching
script from the `DialMouse/` folder:

- **Windows:** double-click `start-windows.bat` (or run it with args).
- **macOS:** double-click `start-macos.command`.
- **Linux:** run `./start-linux.sh`.

With no arguments this runs the **receiver** (Receiver mode). Pass arguments to
the launcher to do other things, e.g. `start-windows.bat --test`.

First launch creates a personal `config.json` from `config.example.json`.

### Verify injection before wiring anything

```
start-windows.bat --test
```

The cursor draws a small square and clicks once — proof that OS-level input
injection works on this machine. (Runs ~10s; `--duration 0` for a single pass.)

### Pick your Mini Mon (the screen on the deck)

```
start-windows.bat --identify        # flashes a number on every display
start-windows.bat --set-minimon N   # save the one on the deck (matched by name)
start-windows.bat --display status  # confirm the right screen is tagged
```

---

## USB layout

```
DialMouse/
  bin/
    dialmouse-win.exe        (Windows)
    dialmouse-macos          (macOS, +x)
    dialmouse-linux          (Linux x86_64, +x)
  tools/                     (optional helper tools, e.g. MultiMonitorTool)
  config.example.json        (documented default)
  config.json                (your settings — created on first run, not shipped)
  start-windows.bat
  start-macos.command
  start-linux.sh
  README.md
```

---

## Common commands

| Command | What it does |
|---|---|
| (no args) | run the receiver (Receiver mode) |
| `--test` | draw a square + click — verify injection |
| `--confine-test` | confine the cursor to the Mini Mon and hold, so you can test it manually |
| `--loopback-test` | send scripted OSC to itself — verify the OSC→cursor pipeline |
| `--identify` / `--set-minimon N` | identify and select the Mini Mon |
| `--display status\|extend\|duplicate\|panic` | display topology (add `--dry-run` to preview) |
| `--mirror N` | mirror display N onto the Mini Mon (needs config, see below) |
| `--hid-test` | open the deck and print dial/key/touch events (no injection) |
| `--hid` | run Direct HID mode |
| `--make-config` | write a fresh `config.json` |
| `--verbose` | DEBUG logging |

Switch the default mode by setting `"mode": "receiver"` or `"hid"` in
`config.json`, or just pass `--hid`.

---

## Per-OS permissions

- **Windows:** none. `SendInput` needs no special permission. SmartScreen may
  warn on the unsigned exe — *More info → Run anyway*.
- **macOS:** grant **Accessibility** (System Settings → Privacy & Security →
  Accessibility). Unsigned binary: right-click `dialmouse-macos` → **Open** once.
  The grant is tied to the binary's path.
- **Linux:** under X11, injection works out of the box. Under Wayland, synthetic
  input is blocked — DialMouse needs `/dev/uinput` access (add yourself to the
  `input` group or install a udev rule). Direct HID also needs raw USB access to
  the deck.

---

## Direct HID notes

Direct HID mode bundles the native HIDAPI library into the binary, so `--hid`
works offline with no extra steps. **Close Companion / the Elgato app first** —
HID access is exclusive. `--hid-test` opens the deck and prints events without
moving the cursor, so you can confirm which dial is which.

## Per-monitor mirror-pick (optional)

Global display modes (`extend` / `duplicate` / `panic`) work out of the box on
Windows. True per-monitor mirror-pick is opt-in: stage a helper such as NirSoft
**MultiMonitorTool** in `tools/`, then set `display.helper_path` and
`display.mirror_command` in `config.json`. Without it, `--mirror` safely no-ops.

---

## Offline acceptance test

The whole point: it must run on a fresh machine with no Python and no internet.
To verify a build:

1. Copy the `DialMouse/` folder to a machine (or a clean user account) that has
   **no Python installed and no network**.
2. `start-<os>` `--test` → cursor draws a square and clicks. ✅ injection works.
3. `start-<os>` (no args) → the receiver starts and binds `127.0.0.1:12000`. ✅
4. With Companion wired (see the setup guide), turn dial 1/2/3 → the cursor
   moves / scrolls; press them → left/right/middle click.
5. Close Companion, `start-<os> --hid-test` → the deck opens and prints dial
   events. ✅ Direct HID works offline.

If all five pass with no internet and no system Python, the offline/USB
requirement is met.

---

## Building from source

You cannot cross-build — run the matching script on each OS (it bundles every
dependency, including the HIDAPI library, into one self-contained binary):

```
packaging/build-windows.ps1     # on Windows  -> dist/USB/DialMouse/
packaging/build-linux.sh        # on Linux
packaging/build-macos.sh        # on macOS
```

Or let CI do all three: the `.github/workflows/build.yml` workflow builds and
uploads per-OS binaries as artifacts (run it manually or push a `v*` tag).

---

## Safety & design

- The listener binds to **127.0.0.1 only**, never the LAN.
- A hang-watchdog force-kills a wedged process; no unbounded buffers; rotating
  logs. Incoming values are clamped/rate-limited so a flood can't run away.
- Confinement uses OS-level cursor clipping (Windows) so a manual mouse is
  contained too — and the OS releases the clip automatically if the process
  dies, so the cursor can never get trapped.
