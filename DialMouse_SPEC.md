# DialMouse — Living Design Document

**This file is the single source of truth for the DialMouse project.**
It supersedes the original PDF where they differ, and records every decision,
the Companion surface layout, the network protocol, the build plan, and a dated
build log.

> **How to keep this "living":** This document is the canonical spec. When you
> want a change, either edit this file yourself and re-upload it to the Project,
> or tell me the change and I'll regenerate this file for you to drop back in.
> The Project stores it; I rewrite it on request. At the end of each build step
> I update the Build Log and hand you a fresh copy.

- **Document version:** v0.10 (Step 6 built: Direct HID mode; pending hardware verify)
- **Last updated:** 2026-06-24
- **Source repository:** https://github.com/Garyz5/DialMouse — clone this at the
  start of each session so the code is in front of us. The verified source is the
  single source of truth for *code*; this file is the single source of truth for
  *decisions*.

---

## 1. Objective & scope

DialMouse turns the rotary dials on an **Elgato Stream Deck + XL** into a
precise "etch-a-sketch" mouse, and (expanded scope) acts as the full input +
display-control layer for a self-contained control surface:

- Dials drive the cursor (Y, X, scroll) and act as mouse buttons.
- A keyboard is built across Companion pages (keystrokes injected by DialMouse).
- The cursor can be **confined to the Mini Mon** (the 1080p monitor mounted on
  the deck) and **detached** to roam all monitors.
- **Monitor switching** changes what the Mini Mon displays (extend vs mirror a
  chosen display).
- Everything is config-driven, runs offline from a USB drive, is multiplatform
  (Windows / macOS / Linux), has comprehensive debug output, and self-terminates
  if it ever hangs.

**Out of scope:** managing Companion itself, or the content shown on the Mini
Mon beyond the topology switches above.

### Scope change vs the original PDF
The PDF declared monitor management out of scope. We have **deliberately pulled
it in**: confinement/detach and Mini-Mon switching are now first-class features.
Everything except the display-topology switching stays cleanly cross-platform;
display switching is inherently OS-specific (see §8).

---

## 2. Hardware & environment

- **Surface:** Elgato Stream Deck + XL — 36 LCD keys, 6 push-dials (360°
  encoders with push), touch strip (1200×100), USB-C. Confirmed to work with
  Bitfocus Companion. Connected via the Elgato USB hub.
- **Control software:** Bitfocus Companion (controls vMix, Ontime, ATEM). The 36
  keys + dials are driven by Companion; DialMouse receives forwarded events.
- **Mini Mon:** a 1920×1080 monitor mounted above the deck.
- **Dev/host machine (current):** Windows 11 24H2 (build 26100), AMD64, virtual
  desktop detected as **7200×1440** (wide multi-monitor rig). System Python is
  3.8.5 — runs Step 1, but the project targets **3.11+** and the shipped
  binaries will bundle 3.11+. Recommend installing a newer Python from
  python.org for development to stay aligned.

---

## 3. Architecture

- **Receiver mode (primary):** Companion forwards dial/key events to DialMouse
  over **localhost OSC/UDP**. DialMouse never opens the deck over HID, so
  Companion keeps full control. DialMouse injects OS-level mouse/keyboard actions
  and runs display switches.
- **Direct HID mode (optional):** when Companion isn't using the deck, DialMouse
  reads the Plus XL directly and emits the same internal events.
- **Event core is identical for both modes:** a front-end (OSC receiver or HID
  reader) emits abstract events → back-ends inject mouse/keyboard actions or run
  display control.
- **Return channel (for button feedback):** DialMouse can send state *back* to
  Companion over OSC (e.g. how many displays are connected, confine on/off) so
  Companion can light/color buttons. This is the most config-heavy part and is
  layered on *after* the core functions work. Functions never depend on the
  lights.

**Safety properties (apply to every module):**
- Listener binds to **127.0.0.1 only**, never the LAN.
- No unbounded buffers; rotating logs; the hang-watchdog covers all threads.
- Incoming values are validated/clamped so a flood can't drive the cursor wild
  or peg CPU.

---

## 4. Locked decisions

| Topic | Decision |
|-------|----------|
| Target OSes | Windows 11, macOS (Apple Silicon + Intel), Linux (X11 primary, Wayland documented) |
| Primary input | Companion → localhost OSC/UDP (Receiver mode) |
| Movement | relative/etch-a-sketch, `pixels_per_tick` + optional acceleration |
| Press behavior | button down on press, up on release (drag-capable); `click_mode` configurable |
| Keyboard | injected by DialMouse via OSC; DialMouse owns shift/layer state |
| Confinement | clamp cursor to the Mini Mon (matched by device **name** so it's resolution-proof); box re-reads live geometry on enable; detach = free roam |
| Monitor switch | armed picker: press Mirror→, displays 1–N light up, tap one to mirror it onto Mini Mon; Extend returns Mini Mon to its own space |
| Pages | Main + Utility 1 + Utility 2 (expandable); **Fn cycles** Main→U1→U2→Main |
| Keyboard order | **QWERTY** on Main |
| Portability | per-OS standalone binaries on USB + launch scripts; no installer; no autorun |
| Networking | localhost only, default UDP **12000**, configurable |
| Stack | Python + pynput (mouse+keyboard) + python-osc + screeninfo; optional hidapi for HID mode |

---

## 5. Companion surface layout

36 keys as a **9×4 grid**. Dials keep the **mouse mapping on every page**, so
switching layers never costs pointer control. **Fn** cycles pages forward; a
**←Main / Back** key returns directly to Main.

> Fn navigation uses Companion's "Set surface to page" action. Default is
> tap-to-cycle; momentary "hold-Fn" is added if your Companion version exposes
> separate dial/key down+up.

### Dial map (all pages)
| Dial | Rotate | Press |
|------|--------|-------|
| 1 | Mouse **Y** (CW=down, CCW=up; invertible) | **Left** click |
| 2 | Mouse **X** (CW=right, CCW=left; invertible) | **Right** click |
| 3 | **Scroll** (CW=down, CCW=up; invertible) | **Middle** click |
| 4 | Sensitivity − / + | reset sensitivity |
| 5 | Scroll speed − / + | toggle scroll direction |
| 6 | fine-jog (optional) | **Pause/resume** DialMouse (kill switch) |

### MAIN page — QWERTY (wrapped every 9 keys)
```
 Q   W   E   R   T   Y   U   I   O
 P   A   S   D   F   G   H   J   K
 L   Z   X   C   V   B   N   M  ⇧Shift
Fn  Esc Tab Spc Ent  ⌫  Ctrl Cfn⇄ ⌖Park
```
- `⇧Shift` — toggles DialMouse shift state (affects letters + symbols).
- `Cfn⇄` — toggle cursor confinement to Mini Mon on/off (detach).
- `⌖Park` — snap cursor to centre of Mini Mon.
- `Fn` — cycle to Utility 1.

### UTILITY 1 page — numbers / symbols / edit / displays
```
 1   2   3   4   5   6   7   8   9      ← also the display-picker targets
 0   -   =   [   ]   ;   '   ,   .
 /  Copy Cut Pst Undo Redo SelA Save Find
←Main ↑   ←   ↓   →  Extend Mirror→ Panic Cfn⇄
```
- `Mirror→` — arm the display picker: keys 1–N light up to show connected
  displays; tap a number to mirror that display onto Mini Mon.
- `Extend` — return Mini Mon to its own extended space.
- `Panic` — force a known-good extended layout (recovery if a switch blanks
  Mini Mon mid-show).
- `Identify` (recommended add) — flashes a number on each monitor so you can
  pick the Mini Mon; with multiple identical-resolution screens this is how you
  disambiguate. `←Main` returns to Main; `Fn` cycles to Utility 2.

### UTILITY 2 page — function keys / macros / media (NEW)
```
 F1  F2  F3  F4  F5  F6  F7  F8  F9
F10 F11 F12 Home End PgUp PgDn Ins Del
DblClk RClk DragLk Snip1 Snip2 Snip3 Vol- Vol+ Mute
←Main  `    \  Precis Turbo NumLk Sens1 Sens2 Fn▶
```
- `DblClk` / `RClk` — dedicated double-click / right-click.
- `DragLk` — drag-lock: press to latch the left button down, press to release
  (drag long distances without holding a dial).
- `Snip1–3` — type canned text snippets (e.g. lower-third names, commands);
  defined in config.
- `Precis` / `Turbo` — temporary precision (slow) / turbo (fast) pointer modes.
- `Sens1` / `Sens2` — jump to saved sensitivity presets.
- `Fn▶` — cycle back to Main (or to Utility 3 once it exists).

> **Expandable:** more utility pages can be added the same way; Fn just adds
> another stop in the cycle. Parking lot for future keys: Win/Cmd, Alt-latch,
> media transport, app-launch, numpad block, screenshot, brightness.

---

## 6. Network protocol (OSC over UDP, 127.0.0.1:12000)

Send **ticks**, not pixels — sensitivity/acceleration live in DialMouse config.
Raw-UDP text fallback (newline-delimited) is supported for the Generic UDP
module. Addresses below; ⬆ marks DialMouse→Companion feedback (return channel).

### Pointer / scroll / buttons
```
/dialmouse/move/x        <int ticks>     relative X (+right / -left)
/dialmouse/move/y        <int ticks>     relative Y (+down / -up)
/dialmouse/scroll        <int ticks>     +down / -up
/dialmouse/button/left   <int 1|0>       1=down, 0=up
/dialmouse/button/right  <int 1|0>
/dialmouse/button/middle <int 1|0>
/dialmouse/click/left                    one-shot (release-less fallback)
/dialmouse/click/right
/dialmouse/click/middle
/dialmouse/click/double                  double left click
/dialmouse/draglock/toggle               latch/unlatch left button
```

### Sensitivity / scroll / control
```
/dialmouse/sensitivity   <int ticks>     adjust pixels_per_tick - / +
/dialmouse/sensitivity/preset <int>      jump to a saved preset
/dialmouse/scrollspeed   <int ticks>     adjust scroll lines per tick - / +
/dialmouse/control/enabled <int 1|0>     pause(0) / resume(1)
/dialmouse/control/toggle                toggle pause
/dialmouse/mode/precision <int 1|0>      precision (slow) hold
/dialmouse/mode/turbo     <int 1|0>      turbo (fast) hold
```

### Confinement / Mini Mon
```
/dialmouse/confine/minimon               lock cursor to Mini Mon
/dialmouse/confine/off                   detach (free roam)
/dialmouse/confine/toggle
/dialmouse/cursor/park                   snap cursor to centre of Mini Mon
/dialmouse/confine/state ⬆  <int 1|0>    feedback: confined?
```

### Keyboard (DialMouse owns shift/layer state)
```
/dialmouse/key/tap   <name>              a, 1, enter, esc, tab, f5, home, ...
/dialmouse/key/down  <name>
/dialmouse/key/up    <name>
/dialmouse/key/type  <string>            canned snippet text
/dialmouse/key/mod/toggle <shift|ctrl|alt|win>
/dialmouse/key/shift/state ⬆ <int 1|0>   feedback: shift latched?
```

### Display control
```
/dialmouse/display/arm                   arm the mirror picker
/dialmouse/display/pick      <int n>     mirror display n onto Mini Mon
/dialmouse/display/extend                Mini Mon = own extended space
/dialmouse/display/preset    <name>      run a config-defined preset
/dialmouse/display/panic                 force known-good extended layout
/dialmouse/display/identify              flash an index number on each monitor
/dialmouse/display/count ⬆   <int n>     feedback: connected display count
/dialmouse/display/armed ⬆   <int 1|0>   feedback: picker armed?
```
*(Addresses are provisional until each step implements and tests them.)*

---

## 7. Config reference

`config.json` lives beside the binary, is documented, and every option is
editable. A documented default ships in the repo and can be regenerated with
`--make-config`. Bad/missing values never crash — they log a warning and fall
back (e.g. a non-localhost `network.host` is forced to `127.0.0.1`).

| Key | Default | Meaning |
|-----|---------|---------|
| `mode` | `"receiver"` | `receiver` (OSC) or `hid` |
| `click_mode` | `"hold"` | `hold` (drag-capable) or `tap` |
| `network.host` | `"127.0.0.1"` | localhost only; forced if set otherwise |
| `network.port` | `12000` | UDP listen port |
| `movement.pixels_per_tick` | `6` | pixels per dial detent |
| `movement.invert_x` / `invert_y` | `false` | per-axis inversion |
| `movement.acceleration.enabled` | `true` | scale fast spins up |
| `movement.acceleration.window_ms` | `40` | ticks within this window accelerate |
| `movement.acceleration.max_factor` | `4.0` | max acceleration multiplier |
| `movement.scroll.lines_per_tick` | `1` | wheel lines per scroll detent |
| `movement.scroll.invert` | `false` | flip scroll direction |
| `confine.default_on` | `false` | start with cursor locked to Mini Mon |
| `confine.minimon.match` | `"resolution"` | how to find Mini Mon: `name`/`index`/`resolution`/`primary` |
| `confine.minimon.name` | `null` | device name match (e.g. `\\.\DISPLAY4`); resolution-proof |
| `confine.minimon.width`/`height` | `1920`/`1080` | resolution to match |
| `confine.minimon.index` | `null` | explicit display index override |
| `watchdog.enabled` | `true` | hang auto-kill on/off |
| `network.max_events_per_sec` | `5000` | flood guard; excess datagrams dropped |
| `watchdog.timeout_s` | `5.0` | seconds before force-kill |
| `keyboard` / `display` | `{}` | reserved for Steps 4/5 |

---

## 8. Cross-platform notes

- **macOS:** needs **Accessibility** permission (maybe Input Monitoring) to
  inject input — unavoidable. Unsigned binary approved via right-click → Open;
  grant is tied to the binary's path. Universal2 build. Display switching via
  Quartz `CGConfigureDisplayMirrorOfDisplay` or staged `displayplacer`.
- **Windows 11:** `SendInput`, no special permission. SmartScreen may warn on
  the unsigned exe (More info → Run anyway). Display switching: built-in
  `DisplaySwitch.exe` does global modes — on **24H2 (build 26100)** use the
  **numeric args** (`2`=duplicate, `3`=extend); the old `/clone` `/extend`
  switches went flaky on 22H2+. Per-monitor mirror (pick which display) needs the
  CCD API (`SetDisplayConfig` via ctypes) or staged NirSoft **MultiMonitorTool**
  (standalone exe, offline-friendly). Note: duplicate / mirror / clone are the
  **same OS operation**.
- **Linux/X11:** XTest injection works; `xrandr` does display switching
  (`--same-as` to mirror, etc.).
- **Linux/Wayland:** XTest blocked → use `/dev/uinput` (needs `input` group or
  the provided udev rule). Display switching has **no universal tool**
  (compositor-specific); documented as the weak spot, not promised.

---

## 9. Build plan & status

Each step is independently runnable/testable before the next.

| # | Step | Status |
|---|------|--------|
| 1 | Foundation: logging, hang-watchdog, platform detection, mouse back-end, `--test` | ✅ done, verified on Windows |
| 2 | Config + movement model (accel/invert) + per-monitor enumeration + **confine/detach engine** | ✅ done |
| 3 | OSC/UDP receiver + event core (wire pointer/scroll/buttons + confine/detach) | ✅ done |
| 4 | Keyboard back-end (inject + shift/layer state) + control surface (pause, sensitivity, precision/turbo, drag-lock, snippets) | ✅ built (pending hardware verify) |
| 5 | Display-control module (extend / mirror-pick / panic) per-OS + return-channel feedback | ✅ built (pending hardware verify) |
| 6 | Direct HID mode (optional) | ✅ built (pending hardware verify) |
| 7 | Packaging: PyInstaller per-OS + GitHub Actions; stage helper tools; USB layout | ☐ |
| 8 | Docs: full single-/multi-page Companion setup guide + README + importable Companion config if feasible | ☐ |

---

## 10. Open questions / parking lot

- Confirm Companion recognizes the Plus XL **surface** and exposes dial
  rotate + press (and ideally separate down/up) on your version.
- Confirm Companion can emit **touch-strip** events for the Plus XL (treated as
  optional polish for now).
- Final symbol set / snippet contents for Utility pages (your call as we build
  Step 4).
- Monitor-switch granularity beyond mirror-pick (e.g. presets that also
  reposition) — revisit at Step 5.

---

## 10b. Next session (Step 7 or 8) — start here

Step 6 is built and unit-verified (91 logic tests). **First, verify Step 6 on
hardware** (checklist in the latest build-log entry) — close Companion, then
`--hid-test` to confirm the deck opens and which dial index is which, then `--hid`
to drive the cursor. Then choose:

- **Step 7 — Packaging:** PyInstaller per-OS one-file binaries + a GitHub Actions
  workflow building all three; bundle the HID backend (hidapi) and stage helper
  tools (MultiMonitorTool); lay out the USB drive (`/DialMouse/bin/...`, launch
  scripts, `config.example.json`, README). This is what makes it the offline
  carry-between-gigs tool.
- **Step 8 — Docs:** the full Companion setup guide (per-dial OSC action table +
  the QWERTY/Utility page build) + README (per-OS quick start, permissions,
  config reference, troubleshooting) + an importable Companion config if feasible.

**Direct HID reality (Step 6 as built):**
- Built on the cross-platform `python-elgato-streamdeck` library (guarded,
  OPTIONAL import): dial turn/press + keys + touch decoded for us. If the library
  or a HID backend is missing, Receiver mode still works; only `--hid` is
  unavailable, with per-OS guidance.
- The dial map is config-driven (`hid.dials`, `hid.invert`) and matches the spec
  defaults; the translator (`hid_map.py`) is pure and fully unit-tested with a
  mock core, so HID and Receiver mode drive the SAME event core identically.
- `--hid-test` opens the deck and prints dial/key/touch events WITHOUT injecting,
  for hardware discovery (which index is which dial, turn direction). `--hid` (or
  `mode: "hid"`) drives the cursor for real.
- HID access is exclusive: Companion and Direct HID cannot hold the deck at once.
- **Unknown:** whether the library recognizes this exact "Plus XL" (36 keys / 6
  dials / touch) device. `--hid-test` will reveal what it enumerates; if it
  doesn't recognize the device, Receiver mode (already verified) remains primary.

---

## 11. Build log

- **2026-06-21 — Step 1 complete.** Foundation built and verified on Windows 11
  24H2: `--test` drew the square + click, bounds auto-detected 7200×1440, clean
  exit. 11/11 pure-logic tests pass. Hang-watchdog force-kill demonstrated
  (exit 2 + thread dump).
- **2026-06-21 — Design consolidated.** Expanded scope (confine/detach, monitor
  switch, keyboard), QWERTY Main + Utility 1 + Utility 2 designed, Fn-cycle
  navigation, OSC protocol drafted incl. return channel. This living document
  created.
- **2026-06-21 — Step 2 complete.** Config system (documented `config.json`,
  validated, localhost forced, never crashes), etch-a-sketch movement model
  (pixels_per_tick + acceleration + per-axis invert + scroll), per-monitor
  enumeration (screeninfo + fallback), and the confine/detach engine.
  New CLI: `--make-config`, `--list-monitors`, `--test --confine`. 26/26
  pure-logic tests pass (11 Step 1 + 15 Step 2). Pending: verify on the 5-monitor
  Windows rig (`--list-monitors` should show all 5; `--test --confine` keeps the
  square inside the Mini Mon).

- **2026-06-21 — Display-identify added (post Step 2).** Discovered the rig has
  three identical 1920x1080 monitors, so resolution-matching can't disambiguate
  the Mini Mon. Added: `--identify` (tkinter overlay showing a big index number
  on every screen), `--set-minimon N` (saves the chosen index to config.json as
  match=index), and `--test --monitor N` plus a confinement edge-ride demo so
  it's visually obvious the cursor is locked to one screen. A future Companion
  "Identify" utility button maps to `/dialmouse/display/identify`. Verified the
  set-minimon write+resolve chain in a simulated 4-monitor rig.

- **2026-06-21 — Confinement made resolution-proof.** Mini Mon is now matched by
  device **name** (e.g. `\\.\DISPLAY4`) rather than resolution, so changing the
  Mini Mon's resolution no longer breaks identification; `--set-minimon N`
  records the name (index as fallback). Confinement re-reads the monitor's live
  geometry every time it's enabled, so the box always matches the current
  resolution. Verified across a simulated 1920x1080 -> 1280x720 change. 18 Step-2
  logic tests pass (29 total with Step 1). Confirmed on hardware: Mini Mon = #2
  (DISPLAY4); edge-ride demo showed the cursor locked to one screen. In live
  use, confinement is a Companion toggle (no timed release; the test simply ends).

- **2026-06-21 — Step 3 complete.** OSC/UDP receiver (own socket bound to
  127.0.0.1 only, ignores non-loopback senders) + event core. Wired: pointer
  move X/Y, scroll, button down/up, one-shot clicks, sensitivity/scrollspeed,
  pause/resume kill-switch, confine/detach/park. Both OSC and the raw-UDP text
  fallback ("dx 1", "left down", "confine toggle", ...) handled on one port.
  Safety: incoming ticks clamped (+/-127), config-driven flood rate-limit
  (network.max_events_per_sec, default 5000, excess dropped), synchronous recv
  loop with no queue (cannot leak), watchdog beat every loop incl. idle. Default
  CLI action now runs the receiver; added --loopback-test (sends scripted OSC to
  itself so cursor moves without Companion) and --port. 40 logic tests pass
  total (incl. a real-socket end-to-end loopback). Next: verify on hardware with
  --loopback-test, then wire Companion (the Step 8 guide) to send these addresses.

- **2026-06-24 — Repo established + Step 4 built.** Project pushed to GitHub
  (https://github.com/Garyz5/DialMouse) so each session can clone the real code
  instead of starting blind; `.gitignore` added, committed `.pyc` bytecode
  removed. Step 4 implemented and unit-verified (62 logic tests pass: 11 + 18 +
  11 Steps 1-3, + 22 new). Delivered:
  - **Watchdog teardown fix (Step 3 carryover):** the fire decision now
    re-checks the stop/pause flags right before the irreversible `os._exit`
    (`_should_fire`), `stop()` pauses first, `main()` pauses the watchdog before
    teardown, and the loopback sender beats it throughout. No more false-fire on
    shutdown.
  - **`--duration SECONDS` (default 15):** `--test` and `--loopback-test` now
    loop for the duration (use `0` for a single pass) so there's time to observe,
    beating the watchdog the whole time.
  - **Keyboard back-end** (`keyboard_backend.py` raw pynput injection +
    `keyboard.py` shift/layer state machine). DialMouse owns shift state: latched
    Shift types the shifted character in software (no physical Shift held);
    inline combos (`ctrl+c`, `shift+tab`) physically hold modifiers around one
    tap for app shortcuts. Wired OSC `/dialmouse/key/{tap,down,up,type,mod/
    toggle,snippet}`; same guarded injection error/guidance as the mouse path.
  - **Control surface:** drag-lock (`/draglock/toggle`, auto-released on pause),
    precision/turbo holds (`/mode/precision|turbo`), sensitivity presets
    (`/sensitivity/preset`, config `movement.sensitivity_presets`), double-click
    (`/click/double`), and config-defined snippets (`keyboard.snippets`). Raw-UDP
    text grammar extended (`key`, `kdown`, `kup`, `mod`, `type`, `snippet`,
    `dblclick`, `draglock`, `preset`, `precision on|off`, `turbo on|off`).
  - Version bumped to 0.4.0; `config.json` + `--make-config` now include the new
    movement/keyboard fields (backward compatible — old configs still load).
  **Pending hardware verification (do first next session):** on the Windows rig,
  run `python -m dialmouse --loopback-test --duration 15` (cursor squares for
  15s, clean exit, no watchdog kill); then wire a few Companion keys to
  `/dialmouse/key/tap` + a `⇧Shift` to `/dialmouse/key/mod/toggle shift` and
  confirm letters/symbols type with correct case, `ctrl+c`/`ctrl+v` work,
  drag-lock latches the left button, and precision/turbo change pointer speed.

- **2026-06-24 — Step 5 built (display control + OSC return channel).** v0.5.0.
  80 logic tests pass (11+18+11+22 Steps 1-4, +18 new). Delivered:
  - **Display back-end** (`display_backend.py`): per-OS topology ops with a
    guarded command runner, dry-run, and graceful no-ops. Windows real
    (`DisplaySwitch.exe 3`=extend, `2`=duplicate, panic=extend); macOS
    (`displayplacer`) and Linux/X11 (`xrandr`) scaffolded best-effort/unverified;
    Wayland documented as the weak spot. **Per-monitor mirror-pick is
    config-driven** (`display.mirror_command` template) and no-ops safely if
    unset, so no untested destructive command ever ships.
  - **Display controller** (`display.py`): armed mirror-picker state machine
    (arm → pick N → auto-disarm), extend/duplicate/panic/preset, each
    re-resolving the Mini Mon afterwards (`confine.refresh()`). `identify` runs
    as a separate process so the tkinter overlay never blocks the receiver.
  - **OSC return channel** (`feedback.py`): optional, de-duped, fire-and-forget
    sender for `/confine/state`, `/key/shift/state`, `/display/count`,
    `/display/armed`. Off unless `display.feedback.enabled`; core never depends
    on it. Wired into the event core at the confine/shift/arm/pick points and
    pushed once at startup via `core.publish_state()`.
  - Wired inbound OSC `/dialmouse/display/{arm,pick,extend,duplicate,preset,
    panic,identify}` + raw-text grammar (`display arm|extend|duplicate|panic|
    identify`, `display pick N`, `display preset NAME`).
  - New CLI for hardware testing without Companion: `--display
    status|extend|duplicate|panic`, `--mirror N`, `--display-preset NAME`,
    `--dry-run`. Typed `display` config section (dry_run, helper_path,
    mirror_command, presets, feedback{enabled,host,port}); `config.json` +
    `--make-config` updated (backward compatible). Also folded in last session's
    `--duration` default 15→10.
  **Pending hardware verification (do first next session):** on the Windows rig,
  `python -m dialmouse --display status` (lists displays + Mini Mon),
  `--display extend --dry-run` then without `--dry-run` (Win+P extend toggles),
  `--display panic` (recovers to extended), and confirm the receiver pushes
  feedback when `display.feedback.enabled` is set + Companion is wired. Dial in
  `display.mirror_command` for true per-monitor mirror-pick on the rig.

- **2026-06-24 — Confinement made real (OS-level clip).** v0.5.1. Fixed a real
  bug surfaced on hardware: confinement only clamped DialMouse-driven motion, so
  a **manually moved physical mouse escaped the Mini Mon**. Added
  `cursor_clip.py` (Windows `ClipCursor` via ctypes; macOS/Linux documented
  no-op for now). `ConfineController` now engages the OS clip on enable, releases
  it on detach, and re-clips on `refresh()` (so it tracks the Mini Mon's live
  geometry after a resolution/topology change). The receiver re-asserts the clip
  each loop (`core.confine_reassert` via a new `UdpReceiver.idle_hook`) so it
  survives focus/desktop changes; Windows auto-releases the clip on process exit,
  so a crash/watchdog-kill can never trap the cursor. New `--confine-test
  [--monitor N] [--duration 10]`: parks the cursor on the Mini Mon and HOLDS
  (no square drawing) so you can move a physical mouse and watch it stay
  contained. 83 logic tests pass (+3 clip-wiring). **Note:** deliverable zips no
  longer include `config.json` (it is user state — the Mini Mon selection — and a
  shipped default was overwriting `--set-minimon`). Verified on hardware that the
  Mini Mon stays name-stable (`\\.\DISPLAY3`) even after its resolution was
  changed to 720x1280.

- **2026-06-24 — Step 6 built (Direct HID mode).** v0.6.0. 91 logic tests pass
  (11+18+11+22+21 Steps 1-5, +8 new). Delivered the optional second front-end:
  read the Plus XL's dials directly over USB when Companion isn't using the deck,
  emitting the SAME internal events into the shared event core (so HID and
  Receiver mode behave identically).
  - **`hid_frontend.py`:** opens the deck via the cross-platform
    `python-elgato-streamdeck` library (guarded, optional import), registers
    dial/key/touch callbacks, runs a watchdog-fed idle loop, and re-asserts the
    confine clip each loop. Fails gracefully with per-OS guidance if the library
    or HID backend is missing, or if the deck is busy (Companion has it — HID is
    exclusive) — Receiver mode still works regardless.
  - **`hid_map.py`:** pure, device-free translator from `(dial, turn/press,
    value)` to event-core calls. Implements the spec dial map (Y/X/scroll +
    L/R/M buttons on dials 1-3; sensitivity/scrollspeed + reset/invert/pause on
    4-6), fully config-driven and unit-tested with a mock core.
  - Added `MovementModel.reset_sensitivity()` / `toggle_scroll_invert()` and the
    EventCore wrappers (for dial-4/5 presses).
  - Typed `hid` config section (`auto_open`, per-dial `dials` map, `invert`),
    validated (unknown actions -> "none"); `config.json` + `config.example.json`
    + `--make-config` updated. `requirements.txt` lists `streamdeck` + `hidapi`
    as OPTIONAL (Receiver mode needs neither).
  - CLI: `--hid` (run Direct HID mode), `--hid-test` (open the deck and print
    dial/key/touch events without injecting — hardware discovery). `mode: "hid"`
    in config also routes the default action to HID.
  **Pending hardware verification (do first next session):** close Companion (HID
  is exclusive), then `python -m dialmouse --hid-test` — confirm the deck opens
  and watch the printed events as you turn/press each dial (note which index is
  which and the turn direction). Then `python -m dialmouse --hid` and confirm
  dial 1 moves the cursor vertically, dial 2 horizontally, dial 3 scrolls, presses
  fire L/R/M, and dial 6 press pauses/resumes. If the library doesn't recognize
  the device, say so — Receiver mode stays primary.
