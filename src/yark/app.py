"""Hold-to-talk listener."""

from __future__ import annotations

import asyncio
import logging
import signal

from yark.config import AppConfig
from yark.hotkey import start_hold_listener
from yark.inject import beep, inject_text
from yark.permissions import check_accessibility
from yark.session import transcribe_until

logger = logging.getLogger("yark")


async def listen(cfg: AppConfig, *, inject_mode: str | None = None) -> None:
    mode = inject_mode or cfg.input.inject
    if mode != "print" and not check_accessibility(prompt=True):
        logger.warning(
            "Accessibility permission is off. Grant it to this terminal in "
            "System Settings → Privacy & Security → Accessibility, then rerun."
        )

    loop = asyncio.get_running_loop()
    stop_listen = asyncio.Event()
    session_stop: asyncio.Event | None = None
    session_task: asyncio.Task | None = None

    def _start_session() -> None:
        nonlocal session_stop, session_task
        if session_task is not None and not session_task.done():
            return
        logger.info("listening (release %s to stop)", cfg.input.hotkey)
        if cfg.input.beep:
            beep()
        session_stop = asyncio.Event()
        session_task = loop.create_task(
            _run_session(cfg, session_stop, mode), name="yark-session"
        )

    def _stop_session() -> None:
        if session_stop is not None and not session_stop.is_set():
            logger.info("stopping")
            session_stop.set()

    def _on_press() -> None:
        loop.call_soon_threadsafe(_start_session)

    def _on_release() -> None:
        loop.call_soon_threadsafe(_stop_session)

    listener = start_hold_listener(
        cfg.input.hotkey, on_press=_on_press, on_release=_on_release
    )
    print(
        f"yark is running. Hold {cfg.input.hotkey} to dictate, Ctrl+C to quit.",
        flush=True,
    )

    def _sigint() -> None:
        stop_listen.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _sigint)
        loop.add_signal_handler(signal.SIGTERM, _sigint)
    except NotImplementedError:
        pass

    try:
        await stop_listen.wait()
    finally:
        if session_stop is not None:
            session_stop.set()
        if session_task is not None:
            try:
                await asyncio.wait_for(session_task, timeout=8)
            except (asyncio.TimeoutError, Exception):
                session_task.cancel()
        listener.stop()
        print("\nyark stopped.", flush=True)


async def _run_session(cfg: AppConfig, stop: asyncio.Event, mode: str) -> None:
    try:
        async for piece in transcribe_until(cfg, stop):
            inject_text(piece, mode)
        if mode == "print":
            print(flush=True)
        if cfg.input.beep:
            beep()
    except Exception:
        logger.exception("dictation session failed")
        if cfg.input.beep:
            beep()
