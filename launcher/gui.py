#!/usr/bin/env python3
"""DialMouse — GUI launcher.

A friendly front door for the verified core binary. It does NOT reimplement
DialMouse: it builds a command line and runs ``bin/dialmouse-<os>``, streaming
the core's log into a pane. This keeps the tested core untouched — the launcher
is pure convenience.

  * Simple view  : a Start/Stop button for the receiver, a status line, and a
                   "Show logs" toggle. Console stays hidden; the log pane is the
                   reachable-if-something-breaks surface.
  * Advanced view: fixed buttons for the test/dev commands (Test, Identify, Set
                   Mini Mon, Confine test, HID test, Loopback) plus a free-text
                   arguments box, so anything the CLI can do is one click away.

The non-UI helpers (binary resolution, command building) are importable and
unit-tested; the Tk UI is only constructed when run directly.
"""

from __future__ import annotations

import os
import platform
import shlex
import sys
from typing import List

APP_TITLE = "DialMouse"
LAUNCHER_VERSION = "1.1"   # bump when the launcher itself changes (shown in title)

# Hide the spawned console child's own window on Windows (its output is piped
# into our log pane instead).
_CREATE_NO_WINDOW = 0x08000000


# --------------------------------------------------------------------------- #
# Pure helpers (no Tk) — unit-tested.
# --------------------------------------------------------------------------- #

def base_dir() -> str:
    """Folder the launcher lives in: the DialMouse/ USB root. When frozen this
    is the exe's directory; from source it's this file's directory."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def core_binary_name(system: str | None = None) -> str:
    system = system or platform.system()
    return {
        "Windows": "dialmouse-win.exe",
        "Darwin": "dialmouse-macos",
        "Linux": "dialmouse-linux",
    }.get(system, "dialmouse-linux")


def core_candidates(base: str, system: str | None = None) -> List[str]:
    """Where the core binary might live, in priority order."""
    name = core_binary_name(system)
    return [os.path.join(base, "bin", name), os.path.join(base, name)]


def resolve_core_command(base: str, system: str | None = None,
                         exists=os.path.exists, frozen: bool | None = None):
    """The command prefix that runs the core, or None if it can't be found.

    Prefers the packaged binary under bin/ (or beside the launcher). Only when
    running from SOURCE does it fall back to ``python -m dialmouse`` — never when
    frozen, because there ``sys.executable`` is THIS launcher, and relaunching it
    would just open another GUI window instead of running the core."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    for candidate in core_candidates(base, system):
        if exists(candidate):
            return [candidate]
    if not frozen:
        return [sys.executable, "-m", "dialmouse"]
    return None


def build_command(core_cmd: List[str], args: List[str]) -> List[str]:
    return list(core_cmd) + list(args)


def parse_extra_args(text: str) -> List[str]:
    """Split a free-text args string the way a shell would, robustly."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text, posix=(os.name != "nt"))
    except ValueError:
        return text.split()


# Advanced command buttons: (label, args, needs_int_prompt)
ADVANCED_COMMANDS = [
    ("Test (square + click)", ["--test"], None),
    ("Identify monitors", ["--identify"], None),
    ("Set Mini Mon…", ["--set-minimon"], "monitor number"),
    ("Confine test", ["--confine-test"], None),
    ("HID test", ["--hid-test"], None),
    ("Loopback test", ["--loopback-test"], None),
]


# --------------------------------------------------------------------------- #
# Tk UI (constructed only when run as a program).
# --------------------------------------------------------------------------- #

def _run_gui() -> int:  # pragma: no cover - requires a display
    import queue
    import shutil
    import subprocess
    import threading
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, simpledialog, ttk

    base = base_dir()
    core_cmd = resolve_core_command(base)
    core_missing = core_cmd is None

    # First run: seed a personal config.json from the shipped example.
    cfg, example = os.path.join(base, "config.json"), os.path.join(base, "config.example.json")
    if not os.path.exists(cfg) and os.path.exists(example):
        try:
            shutil.copyfile(example, cfg)
        except OSError:
            pass

    root = tk.Tk()
    root.title(f"{APP_TITLE}  ·  launcher {LAUNCHER_VERSION}")
    root.minsize(420, 170)

    state = {"proc": None, "advanced": False, "logs": False}
    out_q: "queue.Queue[str]" = queue.Queue()

    # -- layout --
    main = ttk.Frame(root, padding=12)
    main.pack(fill="both", expand=True)

    status = tk.StringVar(value="Idle — press Start to run the receiver.")
    if core_missing:
        status.set("⚠ Core binary not found — run DialMouse from its USB folder.")
    ttk.Label(main, textvariable=status, font=("", 10)).pack(anchor="w", pady=(0, 8))

    row = ttk.Frame(main)
    row.pack(fill="x")
    start_btn = ttk.Button(row, text="▶  Start")
    start_btn.pack(side="left")
    adv_btn = ttk.Button(row, text="Advanced ▾")
    adv_btn.pack(side="right")
    logs_btn = ttk.Button(row, text="Show logs ▾")
    logs_btn.pack(side="right", padx=(0, 8))

    adv = ttk.LabelFrame(main, text="Advanced", padding=8)
    btn_grid = ttk.Frame(adv)
    btn_grid.pack(fill="x")
    adv_buttons = []
    for i, (label, args, prompt) in enumerate(ADVANCED_COMMANDS):
        b = ttk.Button(btn_grid, text=label,
                       command=lambda a=args, p=prompt: launch(a, p))
        b.grid(row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4)
        adv_buttons.append(b)
    btn_grid.columnconfigure(0, weight=1)
    btn_grid.columnconfigure(1, weight=1)

    extra_row = ttk.Frame(adv)
    extra_row.pack(fill="x", pady=(8, 0))
    ttk.Label(extra_row, text="Extra arguments:").pack(side="left")
    extra_var = tk.StringVar()
    extra_entry = ttk.Entry(extra_row, textvariable=extra_var)
    extra_entry.pack(side="left", fill="x", expand=True, padx=6)
    run_btn = ttk.Button(extra_row, text="Run",
                         command=lambda: launch(parse_extra_args(extra_var.get()), None))
    run_btn.pack(side="left")
    edit_btn = ttk.Button(adv, text="Edit config.json", command=lambda: _open_config(base))
    edit_btn.pack(anchor="w", pady=(8, 0))
    adv_buttons += [run_btn, edit_btn]

    log_frame = ttk.Frame(main)
    log = scrolledtext.ScrolledText(log_frame, height=14, width=72, wrap="word",
                                    state="disabled", font=("Consolas", 9))
    log.pack(fill="both", expand=True)
    ttk.Button(log_frame, text="Clear", command=lambda: _clear_log()).pack(anchor="e", pady=(4, 0))

    # -- helpers --
    def _append(text: str) -> None:
        log.configure(state="normal")
        log.insert("end", text)
        log.see("end")
        log.configure(state="disabled")

    def _clear_log() -> None:
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")

    def _set_running(running: bool, what: str = "") -> None:
        start_btn.configure(text="■  Stop" if running else "▶  Start")
        for b in adv_buttons:
            b.configure(state="disabled" if running else "normal")
        if running:
            status.set(f"Running: {what}")
        else:
            status.set("Idle — press Start to run the receiver.")

    def _reader(proc) -> None:
        try:
            for line in iter(proc.stdout.readline, ""):
                out_q.put(line)
        finally:
            out_q.put(None)  # sentinel: process output ended

    def launch(args, prompt) -> None:
        if core_missing:
            messagebox.showerror(
                APP_TITLE,
                "Could not find the DialMouse core binary.\n\nExpected at:\n  "
                + "\n  ".join(core_candidates(base))
                + "\n\nMake sure you're running DialMouse from the folder that "
                  "contains the bin\\ directory.")
            return
        if state["proc"] is not None:
            messagebox.showinfo(APP_TITLE, "Something is already running. Press Stop first.")
            return
        if prompt:
            n = simpledialog.askinteger(APP_TITLE, f"Enter {prompt}:", parent=root, minvalue=0)
            if n is None:
                return
            args = list(args) + [str(n)]
        cmd = build_command(core_cmd, args)
        if not state["logs"]:
            _toggle_logs(force=True)  # auto-reveal logs so the user sees output
        _append(f"$ {' '.join(cmd)}\n")
        creation = _CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        try:
            proc = subprocess.Popen(
                cmd, cwd=base, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=creation)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not start DialMouse:\n{exc}")
            return
        state["proc"] = proc
        _set_running(True, " ".join(args) if args else "receiver")
        threading.Thread(target=_reader, args=(proc,), daemon=True).start()

    def stop() -> None:
        proc = state["proc"]
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass

        def _force_kill():
            if proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
        root.after(3000, _force_kill)

    def on_start() -> None:
        if state["proc"] is None:
            launch([], None)        # no args = receiver
        else:
            stop()

    start_btn.configure(command=on_start)

    def _toggle_advanced() -> None:
        state["advanced"] = not state["advanced"]
        if state["advanced"]:
            adv.pack(fill="x", pady=(10, 0), before=log_frame if state["logs"] else None)
            adv_btn.configure(text="Advanced ▴")
        else:
            adv.pack_forget()
            adv_btn.configure(text="Advanced ▾")

    def _toggle_logs(force: bool = False) -> None:
        state["logs"] = True if force else not state["logs"]
        if state["logs"]:
            log_frame.pack(fill="both", expand=True, pady=(10, 0))
            logs_btn.configure(text="Hide logs ▴")
        else:
            log_frame.pack_forget()
            logs_btn.configure(text="Show logs ▾")

    adv_btn.configure(command=_toggle_advanced)
    logs_btn.configure(command=_toggle_logs)

    def _drain() -> None:
        try:
            while True:
                item = out_q.get_nowait()
                if item is None:
                    state["proc"] = None
                    _append("[process ended]\n")
                    _set_running(False)
                else:
                    _append(item)
        except queue.Empty:
            pass
        root.after(100, _drain)

    def on_close() -> None:
        if state["proc"] is not None:
            stop()
            root.after(300, root.destroy)
        else:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(100, _drain)
    # Test hook: build the whole UI then exit, for headless/CI construction checks.
    if os.environ.get("DIALMOUSE_GUI_SELFTEST"):
        root.after(600, root.destroy)
    root.mainloop()
    return 0


def _open_config(base: str) -> None:  # pragma: no cover
    path = os.path.join(base, "config.json")
    try:
        if platform.system() == "Windows":
            os.startfile(path)  # noqa: S606
        elif platform.system() == "Darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def main() -> int:
    return _run_gui()


if __name__ == "__main__":
    sys.exit(main())
