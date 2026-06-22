"""Display identification overlay.

Shows a large index number on each monitor at once (like the Windows "Identify"
button) so you can see which physical screen maps to which index, then set
``confine.minimon.index`` accordingly.

Uses tkinter, which ships with CPython on Windows and macOS (and is bundled into
the packaged binary). If tkinter is unavailable (some minimal Linux installs),
``show_identify`` returns False and the caller falls back to the dependency-free
``--test --monitor N`` method.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .monitors import Monitor

# A small palette so each screen is visually distinct.
_COLORS = ["#1565c0", "#2e7d32", "#c62828", "#6a1b9a", "#ef6c00", "#00838f",
           "#4527a0", "#ad1457"]


def show_identify(
    monitors: List[Monitor],
    seconds: float = 6.0,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """Flash an index number on every monitor for ``seconds``. Returns success."""
    log = logger or logging.getLogger("dialmouse")
    if not monitors:
        log.error("No monitors to identify.")
        return False
    try:
        import tkinter as tk
    except Exception as exc:
        log.warning("tkinter unavailable (%s); cannot show the overlay. "
                    "Use --test --monitor N instead.", exc)
        return False

    try:
        root = tk.Tk()
        root.withdraw()  # hide the dummy root; we use a Toplevel per monitor.
        windows = []
        for m in monitors:
            color = _COLORS[m.index % len(_COLORS)]
            w = tk.Toplevel(root)
            w.overrideredirect(True)          # no title bar / borders
            w.attributes("-topmost", True)
            # Size a centered banner on each monitor (not full-screen, so it's
            # clearly an overlay and works even with negative origins nearby).
            bw, bh = min(m.width, 520), min(m.height, 300)
            bx = m.x + (m.width - bw) // 2
            by = m.y + (m.height - bh) // 2
            w.geometry(f"{bw}x{bh}+{bx}+{by}")
            w.configure(bg=color)
            primary = "  (PRIMARY)" if m.is_primary else ""
            tk.Label(w, text=str(m.index), fg="white", bg=color,
                     font=("Segoe UI", 160, "bold")).pack(expand=True)
            tk.Label(w, text=f"display #{m.index} - {m.width}x{m.height}{primary}\n"
                             f"{m.name}\nset confine.minimon.index: {m.index}",
                     fg="white", bg=color, font=("Segoe UI", 14)).pack(pady=(0, 18))
            windows.append(w)

        root.after(int(seconds * 1000), root.destroy)
        log.info("Showing identify overlay on %d display(s) for %.0fs...",
                 len(monitors), seconds)
        root.mainloop()
        return True
    except Exception as exc:
        log.error("Identify overlay failed: %s", exc)
        return False
