"""DialMouse — turn Stream Deck + XL dials into an etch-a-sketch mouse.

This package is built in verified increments. Step 1 (this milestone) provides
the foundation only:

    * structured logging / debug output        (logsetup.py)
    * a hang-watchdog that force-kills a wedged process   (watchdog.py)
    * cross-platform environment detection      (platform_info.py)
    * a relative-only mouse back-end with on-screen bounds clamping
                                                (mouse_backend.py + virtual_desktop.py)
    * a `--test` self-check that draws a visible square and clicks once
                                                (__main__.py)

Later steps add the config system, the OSC/UDP receiver (Receiver mode), the
control surface, optional Direct HID mode, packaging, and docs.
"""

__version__ = "0.4.0"  # Step 4: keyboard back-end + control surface
__app_name__ = "DialMouse"

# Process exit codes. Stable across the whole project so launch scripts and the
# watchdog can act on them deterministically.
EXIT_OK = 0
EXIT_ERROR = 1          # generic unhandled error
EXIT_HANG = 2           # watchdog force-killed a wedged process
EXIT_INJECTION = 3      # mouse injection unavailable (permissions / no display)
EXIT_INTERRUPTED = 130  # Ctrl-C / SIGINT (conventional 128 + SIGINT)
