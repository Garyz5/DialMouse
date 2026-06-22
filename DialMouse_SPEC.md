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

- **Document version:** v0.6 (Step 3 complete)
- **Last updated:** 2026-06-21

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
| 4 | Keyboard back-end (inject + shift/layer state) + control surface (pause, sensitivity, precision/turbo, drag-lock, snippets) | ☐ |
| 5 | Display-control module (extend / mirror-pick / panic) per-OS + return-channel feedback | ☐ |
| 6 | Direct HID mode (optional) | ☐ |
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
