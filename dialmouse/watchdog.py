"""Hang watchdog: automatically kill the process if the main loop stops responding.

Requirement: "it will automatically kill its instance when or if it starts to
hang." This module implements that as a heartbeat watchdog.

How it works
------------
* The main thread calls ``watchdog.beat()`` frequently (each loop iteration /
  each handled event). ``beat()`` is intentionally trivial: it stores the
  current monotonic time. That single assignment is atomic in CPython, so no
  lock is needed and ``beat()`` adds negligible overhead.
* A separate **daemon** thread wakes every ``check_interval`` seconds and looks
  at how long it has been since the last beat. If that exceeds ``timeout`` the
  main loop is presumed wedged.
* On a detected hang we dump every thread's stack (so we can see *where* it
  hung — useful while refining), then force-terminate with ``os._exit``.

Why ``os._exit`` and not ``sys.exit``? If the main thread is stuck (deadlock,
blocking syscall, infinite loop), a normal exit raised on it can never run.
``os._exit`` is issued from the healthy watchdog thread and terminates the
process immediately, which is exactly the "kill a hung instance" behavior we
want. The trade-off — no atexit handlers — is acceptable: by definition we are
already in a bad state, and our only external resource (a localhost UDP socket,
added in a later step) is released by the OS on process death.

Memory safety: the watchdog stores exactly one timestamp. There are no queues
or growing buffers, so it cannot leak.

Long, *intentional* blocking (e.g. a sleep in the self-test) is handled with
``pause()`` / ``resume()`` or the ``paused()`` context manager so it does not
trip a false positive.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional

from . import EXIT_HANG
from .logsetup import get_logger

# Sensible defaults. The timeout is deliberately generous: dial events arrive in
# bursts and we never want to kill a healthy-but-idle process. Idleness is fine
# because the main loop beats on a timer even when no input arrives (wired up in
# a later step); for Step 1 the watchdog mainly guards the self-test.
DEFAULT_TIMEOUT_S = 5.0
DEFAULT_CHECK_INTERVAL_S = 0.5


class Watchdog:
    """A heartbeat-based hang detector that force-kills a wedged process."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT_S,
        check_interval: float = DEFAULT_CHECK_INTERVAL_S,
        on_hang: Optional[Callable[[float], None]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("watchdog timeout must be > 0")
        if check_interval <= 0:
            raise ValueError("watchdog check_interval must be > 0")

        self._timeout = float(timeout)
        self._check_interval = float(check_interval)
        # on_hang is injectable so tests can verify detection without killing the
        # test runner. Production default force-exits.
        self._on_hang = on_hang or self._default_on_hang
        self._log = logger or get_logger()

        self._last_beat = time.monotonic()
        self._paused = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the background watchdog thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        # Enable faulthandler so a hard hang can still dump tracebacks.
        if not faulthandler.is_enabled():
            faulthandler.enable()
        self.beat()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="dialmouse-watchdog", daemon=True
        )
        self._thread.start()
        self._log.debug(
            "Watchdog started (timeout=%.1fs, check every %.1fs).",
            self._timeout, self._check_interval,
        )

    def stop(self) -> None:
        """Stop the watchdog thread cleanly (used on normal shutdown)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._check_interval * 2)
        self._thread = None
        self._log.debug("Watchdog stopped.")

    # -- heartbeat ---------------------------------------------------------

    def beat(self) -> None:
        """Record liveness. Call this from the main loop as often as is cheap."""
        self._last_beat = time.monotonic()

    def pause(self) -> None:
        """Suspend hang detection around a known-long, intentional operation."""
        self._paused = True
        self._log.debug("Watchdog paused.")

    def resume(self) -> None:
        """Resume hang detection and reset the heartbeat clock."""
        self.beat()
        self._paused = False
        self._log.debug("Watchdog resumed.")

    @contextmanager
    def paused(self):
        """Context manager form of pause()/resume()."""
        self.pause()
        try:
            yield
        finally:
            self.resume()

    # -- internals ---------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.wait(self._check_interval):
            if self._paused:
                continue
            elapsed = time.monotonic() - self._last_beat
            if elapsed > self._timeout:
                # Hand off to the configured handler. The default never returns.
                self._on_hang(elapsed)
                return

    def _default_on_hang(self, elapsed: float) -> None:
        msg = (
            f"WATCHDOG: main loop unresponsive for {elapsed:.1f}s "
            f"(timeout {self._timeout:.1f}s). Force-terminating."
        )
        # Log via the logger AND straight to stderr, because the logging path
        # itself could be implicated in the hang.
        try:
            self._log.critical(msg)
        except Exception:  # pragma: no cover - defensive
            pass
        print(msg, file=sys.stderr, flush=True)
        try:
            print("--- thread stacks at hang ---", file=sys.stderr, flush=True)
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        except Exception:  # pragma: no cover - defensive
            pass
        # Immediate, unconditional process death from the healthy thread.
        os._exit(EXIT_HANG)
