"""DialMouse command-line entry point (Step 3: OSC receiver + event core).

Default action (no flags) RUNS THE RECEIVER: it listens on localhost for OSC/UDP
from Companion and drives the cursor. Other actions:

    python -m dialmouse                       # run the receiver (Receiver mode)
    python -m dialmouse --loopback-test [--duration 10]   # OSC -> cursor, no Companion
    python -m dialmouse --make-config
    python -m dialmouse --list-monitors
    python -m dialmouse --identify
    python -m dialmouse --set-minimon N
    python -m dialmouse --test [--confine] [--monitor N] [--duration 10]
    python -m dialmouse --confine-test [--monitor N] [--duration 10]   # confine + HOLD
    python -m dialmouse --display status|extend|duplicate|panic [--dry-run]
    python -m dialmouse --mirror N [--dry-run]      # mirror display N -> Mini Mon
    python -m dialmouse --version
"""

from __future__ import annotations

import argparse
import signal
import socket
import sys
import threading
import time
from pathlib import Path

from . import (
    EXIT_ERROR,
    EXIT_INJECTION,
    EXIT_INTERRUPTED,
    EXIT_OK,
    __app_name__,
    __version__,
)
from . import platform_info
from . import protocol as P
from .config import (
    CONFIG_FILENAME,
    ConfineConfig,
    MiniMonConfig,
    default_config_dict,
    load_config,
    write_default_config,
)
from .confine import ConfineController
from .display import DisplayController
from .display_backend import make_display_backend
from .events import EventCore
from .feedback import FeedbackSender
from .identify import show_identify
from .keyboard import KeyboardController
from .keyboard_backend import KeyboardBackend
from .logsetup import setup_logging
from .monitors import enumerate_monitors, monitor_by_index, pick_minimon
from .mouse_backend import DialMouseInjectionError, MouseBackend
from .movement import MovementModel
from .server import UdpReceiver
from .watchdog import Watchdog


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dialmouse",
        description=f"{__app_name__} -- Stream Deck + XL dials as an etch-a-sketch mouse.",
    )
    p.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="show DEBUG output")
    p.add_argument("--config", type=Path, default=None, metavar="FILE")
    p.add_argument("--port", type=int, default=None, metavar="PORT",
                   help="override the UDP listen port (default from config / 12000)")
    p.add_argument("--make-config", action="store_true")
    p.add_argument("--list-monitors", action="store_true")
    p.add_argument("--identify", nargs="?", type=float, const=6.0, default=None, metavar="SECONDS")
    p.add_argument("--set-minimon", type=int, default=None, metavar="N")
    p.add_argument("--test", action="store_true",
                   help="self-check: draw a square + click (no network)")
    p.add_argument("--confine", action="store_true", help="with --test: confine to Mini Mon")
    p.add_argument("--confine-test", action="store_true",
                   help="confine the cursor to the Mini Mon and HOLD (no square); "
                        "move your mouse to verify it stays contained")
    p.add_argument("--monitor", type=int, default=None, metavar="N", help="with --test: target monitor N")
    p.add_argument("--loopback-test", action="store_true",
                   help="run the receiver and send it scripted OSC; cursor should move")
    p.add_argument("--duration", type=float, default=10.0, metavar="SECONDS",
                   help="how long --test / --loopback-test run so you can observe "
                        "(default 10; use 0 for a single pass)")
    p.add_argument("--display", choices=["status", "extend", "duplicate", "panic"],
                   default=None, help="run a display action then exit (no network)")
    p.add_argument("--mirror", type=int, default=None, metavar="N",
                   help="mirror display N onto the Mini Mon (CLI test of mirror-pick)")
    p.add_argument("--display-preset", default=None, metavar="NAME",
                   help="run a config-defined display preset then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="with display actions: log the exact command without running it")
    p.add_argument("--no-watchdog", action="store_true")
    p.add_argument("--log-dir", type=Path, default=None, metavar="DIR")
    return p


def _default_config_path(explicit):
    if explicit is not None:
        return explicit
    here = Path.cwd() / CONFIG_FILENAME
    return here if here.exists() else None


def _log_environment(logger) -> None:
    env = platform_info.gather_environment()
    logger.debug("--- environment ---")
    for line in env.as_lines():
        logger.debug("  %s", line)
    logger.debug("-------------------")


def _movement_from_config(cfg) -> MovementModel:
    m = cfg.movement
    return MovementModel(
        pixels_per_tick=m.pixels_per_tick,
        invert_x=m.invert_x, invert_y=m.invert_y,
        accel_enabled=m.accel.enabled, accel_window_ms=m.accel.window_ms,
        accel_max=m.accel.max_factor,
        scroll_lines_per_tick=m.scroll.lines_per_tick, scroll_invert=m.scroll.invert,
        precision_factor=m.precision_factor, turbo_factor=m.turbo_factor,
        sensitivity_presets=m.sensitivity_presets,
    )


def _build_runtime(config, logger, dry_run_override=False):
    """Construct movement, confinement, backends, keyboard, display, feedback,
    and the event core that ties them together."""
    movement = _movement_from_config(config)
    confine = ConfineController(config.confine)
    backend = MouseBackend(logger=logger, region_provider=confine.active_region)
    kb_backend = KeyboardBackend(logger=logger)
    keyboard = KeyboardController(kb_backend, snippets=config.keyboard.snippets, logger=logger)

    dcfg = config.display
    dry = dcfg.dry_run or dry_run_override
    dbackend = make_display_backend(dry_run=dry, mirror_command=dcfg.mirror_command,
                                    helper_path=dcfg.helper_path, logger=logger)
    display = DisplayController(dbackend, confine=confine, presets=dcfg.presets, logger=logger)
    feedback = FeedbackSender(host=dcfg.feedback.host, port=dcfg.feedback.port,
                              enabled=dcfg.feedback.enabled, logger=logger)

    core = EventCore(movement, backend, confine, enabled=True, logger=logger,
                     keyboard=keyboard, display=display, feedback=feedback)
    return movement, confine, backend, core, display, feedback


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def _cmd_list_monitors(logger, config) -> int:
    monitors = enumerate_monitors()
    if not monitors:
        logger.error("No monitors detected (headless session?).")
        return EXIT_ERROR
    minimon = pick_minimon(monitors, config.confine.minimon)
    print(f"\nDetected {len(monitors)} display(s):")
    for m in monitors:
        tag = "  <-- Mini Mon (current pick)" if minimon and m.index == minimon.index else ""
        print("  " + m.describe() + tag)
    print("\nIf the wrong screen is tagged, run:  --identify   then   --set-minimon N\n")
    return EXIT_OK


def _cmd_set_minimon(logger, args, index: int) -> int:
    monitors = enumerate_monitors()
    target = monitor_by_index(monitors, index)
    if not target:
        logger.error("No monitor with index %d (have %d). Run --list-monitors.", index, len(monitors))
        return EXIT_ERROR
    dest = args.config or (Path.cwd() / CONFIG_FILENAME)
    import json
    if dest.exists():
        try:
            data = json.loads(dest.read_text(encoding="utf-8"))
        except Exception:
            data = default_config_dict()
    else:
        data = default_config_dict()
    mm = data.setdefault("confine", {}).setdefault("minimon", {})
    if target.name:
        mm["match"] = "name"; mm["name"] = target.name
    else:
        mm["match"] = "index"; mm["name"] = None
    mm["index"] = index
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    how = f"name {target.name!r}" if target.name else f"index {index}"
    logger.info("Saved Mini Mon = display #%d (by %s) to %s.", index, how, dest)
    return EXIT_OK


def _resolve_test_confine(config, monitor_index):
    if monitor_index is not None:
        cfg = ConfineConfig(default_on=False, minimon=MiniMonConfig(match="index", index=monitor_index))
        return ConfineController(cfg)
    return ConfineController(config.confine)


def _send_osc(sock, host, port, address, *args):
    from pythonosc.osc_message_builder import OscMessageBuilder
    b = OscMessageBuilder(address=address)
    for a in args:
        b.add_arg(a)
    sock.sendto(b.build().dgram, (host, port))


def _cmd_loopback_test(logger, config, port, watchdog, duration) -> int:
    """Start the receiver and send it scripted OSC; the cursor should move.

    Loops the scripted square for ``duration`` seconds (default 15) so there's
    time to watch and poke, beating the watchdog throughout so a long, healthy
    run is never mistaken for a hang.
    """
    movement, confine, backend, core, display, feedback = _build_runtime(config, logger)
    try:
        backend.preflight()  # fail fast with clear guidance if no display/perm
    except DialMouseInjectionError as exc:
        logger.error("%s", exc)
        if exc.guidance:
            logger.error("How to fix:\n%s", exc.guidance)
        return EXIT_INJECTION

    rx = UdpReceiver(core, host=config.network.host, port=port,
                     heartbeat=(watchdog.beat if watchdog else None),
                     max_events_per_sec=config.network.max_events_per_sec, logger=logger)
    rx.open()
    t = threading.Thread(target=rx.run, name="dialmouse-rx", daemon=True)
    t.start()

    host = config.network.host
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    deadline = time.monotonic() + max(0.0, float(duration))
    logger.info("Loopback test: sending scripted OSC for %.0fs; watch the cursor.",
                max(0.0, float(duration)))

    def beat():
        if watchdog:
            watchdog.beat()

    try:
        passes = 0
        # Always run at least one full pass; repeat until the deadline.
        while True:
            for _ in range(20):
                _send_osc(s, host, port, P.MOVE_X, 1); beat(); time.sleep(0.01)
            for _ in range(20):
                _send_osc(s, host, port, P.MOVE_Y, 1); beat(); time.sleep(0.01)
            for _ in range(20):
                _send_osc(s, host, port, P.MOVE_X, -1); beat(); time.sleep(0.01)
            for _ in range(20):
                _send_osc(s, host, port, P.MOVE_Y, -1); beat(); time.sleep(0.01)
            passes += 1
            if time.monotonic() >= deadline:
                break
        # One click + one scroll at the very end (kept out of the loop so we
        # don't spam clicks on whatever is under the cursor while you watch).
        time.sleep(0.1); beat()
        _send_osc(s, host, port, P.CLICK_LEFT)
        time.sleep(0.1); beat()
        _send_osc(s, host, port, P.SCROLL, -2)
        time.sleep(0.2); beat()
        logger.info("Sent %d square pass(es).", passes)
    finally:
        # Pause the watchdog BEFORE tearing down: the receiver thread stops
        # beating once we stop it, and we must not be force-killed mid-shutdown.
        if watchdog:
            watchdog.pause()
        s.close()
        rx.stop()
        t.join(timeout=1.0)
    logger.info("Loopback test complete: OSC -> cursor pipeline works.")
    return EXIT_OK


def _cmd_display(logger, config, args) -> int:
    """CLI display actions for hardware testing without Companion."""
    confine = ConfineController(config.confine)
    dcfg = config.display
    dry = dcfg.dry_run or args.dry_run
    backend = make_display_backend(dry_run=dry, mirror_command=dcfg.mirror_command,
                                   helper_path=dcfg.helper_path, logger=logger)
    disp = DisplayController(backend, confine=confine, presets=dcfg.presets, logger=logger)

    if args.mirror is not None:
        disp.arm()
        return EXIT_OK if disp.pick(args.mirror) else EXIT_ERROR
    if args.display_preset:
        return EXIT_OK if disp.preset(args.display_preset) else EXIT_ERROR
    if args.display == "status":
        monitors = enumerate_monitors()
        mm = confine.minimon
        print(f"\nDisplays detected: {len(monitors)}")
        for m in monitors:
            tag = "  <-- Mini Mon" if mm and m.index == mm.index else ""
            print("  " + m.describe() + tag)
        print(f"\nPicker armed : {disp.armed}")
        print(f"Dry-run      : {dry}")
        print(f"Mirror cmd   : {dcfg.mirror_command or '(not configured)'}")
        print(f"Presets      : {', '.join(dcfg.presets) or '(none)'}\n")
        return EXIT_OK
    fn = {"extend": disp.extend, "duplicate": disp.duplicate, "panic": disp.panic}.get(args.display)
    if fn is None:
        logger.error("Unknown display action.")
        return EXIT_ERROR
    return EXIT_OK if fn() else EXIT_ERROR


def _cmd_confine_test(logger, config, watchdog, args) -> int:
    """Confine the cursor to the Mini Mon and HOLD — no square drawing. Park the
    cursor onto the Mini Mon, engage the OS-level clip, then idle for the
    duration so you can move your physical mouse and watch it stay contained."""
    confine = _resolve_test_confine(config, args.monitor)
    backend = MouseBackend(logger=logger, region_provider=confine.active_region)
    try:
        backend.preflight()
    except DialMouseInjectionError as exc:
        logger.error("%s", exc)
        if exc.guidance:
            logger.error("How to fix:\n%s", exc.guidance)
        return EXIT_INJECTION

    if not confine.enable():
        logger.error("Could not confine: no Mini Mon resolved. Run --identify / --set-minimon.")
        return EXIT_ERROR
    target = confine.park_target()
    if target is not None:
        backend.move_to(*target)   # start inside the Mini Mon

    duration = max(0.0, args.duration)
    logger.info("Confined to the Mini Mon. MOVE YOUR MOUSE — it should stay on that "
                "screen for %.0fs. Ctrl-C to stop early.", duration)
    deadline = time.monotonic() + duration
    try:
        # Re-assert the clip frequently so it survives focus changes, and beat
        # the watchdog throughout. No motion is injected — this is purely a hold.
        while time.monotonic() < deadline:
            confine.reassert_clip()
            if watchdog:
                watchdog.beat()
            time.sleep(0.05)
    except KeyboardInterrupt:
        logger.info("Stopped early.")
    finally:
        confine.disable()   # release the clip so the cursor is free again
    logger.info("Confine-hold test complete; cursor released.")
    return EXIT_OK


def _cmd_run_receiver(logger, config, port, watchdog) -> int:
    movement, confine, backend, core, display, feedback = _build_runtime(config, logger)
    try:
        backend.preflight()
    except DialMouseInjectionError as exc:
        logger.error("%s", exc)
        if exc.guidance:
            logger.error("How to fix:\n%s", exc.guidance)
        return EXIT_INJECTION
    if config.confine.default_on:
        core.confine_minimon()
    core.publish_state()   # push initial state to Companion if feedback is on
    rx = UdpReceiver(core, host=config.network.host, port=port,
                     heartbeat=(watchdog.beat if watchdog else None),
                     max_events_per_sec=config.network.max_events_per_sec, logger=logger,
                     idle_hook=core.confine_reassert)
    try:
        rx.open()
    except OSError as exc:
        logger.error("%s", exc)
        return EXIT_ERROR
    logger.info("Press Ctrl-C to stop.")
    try:
        rx.run()
    except KeyboardInterrupt:
        logger.info("Interrupted; stopping receiver.")
    finally:
        rx.stop()
        feedback.close()
    return EXIT_OK


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    logger = setup_logging(verbose=args.verbose, log_dir=args.log_dir)
    logger.info("%s %s starting.", __app_name__, __version__)
    _log_environment(logger)

    if args.make_config:
        target = args.config or (Path.cwd() / CONFIG_FILENAME)
        if target.exists():
            logger.warning("%s already exists; not overwriting.", target)
            return EXIT_ERROR
        write_default_config(target)
        return EXIT_OK

    if args.set_minimon is not None:
        return _cmd_set_minimon(logger, args, args.set_minimon)

    config = load_config(_default_config_path(args.config))
    port = args.port if args.port is not None else config.network.port

    def _handle_signal(signum, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    watchdog = None
    if not args.no_watchdog and config.watchdog.enabled:
        watchdog = Watchdog(timeout=config.watchdog.timeout_s, logger=logger)
        watchdog.start()

    try:
        if args.list_monitors:
            return _cmd_list_monitors(logger, config)

        if args.identify is not None:
            monitors = enumerate_monitors()
            if watchdog:
                watchdog.pause()
            ok = show_identify(monitors, seconds=args.identify, logger=logger)
            if watchdog:
                watchdog.resume()
            if ok:
                logger.info("Note the number on your Mini Mon, then: --set-minimon N")
            return EXIT_OK if ok else EXIT_ERROR

        if args.test:
            confine = _resolve_test_confine(config, args.monitor)
            if args.confine:
                confine.enable()
            backend = MouseBackend(logger=logger, region_provider=confine.active_region)
            start_at = confine.park_target() if (confine.is_confined or args.monitor is not None) else None
            deadline = time.monotonic() + max(0.0, args.duration)
            passes = 0
            while True:
                backend.self_test(heartbeat=(watchdog.beat if watchdog else None),
                                  start_at=start_at, demo_bounds=confine.is_confined)
                passes += 1
                if watchdog:
                    watchdog.beat()
                if time.monotonic() >= deadline:
                    break
            logger.info("Self-test passed (%d pass(es)). Injection works on this machine.", passes)
            return EXIT_OK

        if args.confine_test:
            return _cmd_confine_test(logger, config, watchdog, args)

        if args.loopback_test:
            return _cmd_loopback_test(logger, config, port, watchdog, args.duration)

        if args.display is not None or args.mirror is not None or args.display_preset is not None:
            return _cmd_display(logger, config, args)

        # Default: run the receiver.
        return _cmd_run_receiver(logger, config, port, watchdog)

    except DialMouseInjectionError as exc:
        logger.error("%s", exc)
        if exc.guidance:
            logger.error("How to fix:\n%s", exc.guidance)
        return EXIT_INJECTION
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        return EXIT_INTERRUPTED
    except Exception:
        logger.exception("Unexpected error.")
        return EXIT_ERROR
    finally:
        if watchdog is not None:
            # Pause before stop so nothing can be force-killed during teardown.
            watchdog.pause()
            watchdog.stop()


if __name__ == "__main__":
    sys.exit(main())
