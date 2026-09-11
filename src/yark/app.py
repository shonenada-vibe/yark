"""Hold-to-talk listener and macOS menu-bar runtime."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import threading
from collections.abc import Callable
from dataclasses import replace

from yark.config import AppConfig, LlmConfig, config_path_for_write, save_hotkey, save_llm_config
from yark.hotkey import HoldListener, hotkey_label, resolve_hotkey
from yark.inject import beep, inject_text
from yark.llm import LlmPipeline
from yark.permissions import check_accessibility
from yark.session import transcribe_until

logger = logging.getLogger("yark")


class DictationRuntime:
    """Hotkey + dictation sessions. Cocoa talks to this; no AppKit here."""

    def __init__(self, cfg: AppConfig, inject_mode: str, loop: asyncio.AbstractEventLoop):
        self.cfg = cfg
        self.mode = inject_mode
        self.loop = loop
        self.on_listening: Callable[[bool], None] = lambda _listening: None
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._hold = HoldListener(self._on_press, self._on_release)

    @property
    def hotkey(self) -> str:
        return self.cfg.input.hotkey

    def start(self) -> None:
        if self.mode != "print" and not check_accessibility(prompt=True):
            logger.warning(
                "Accessibility permission is off. Grant it to this terminal in "
                "System Settings → Privacy & Security → Accessibility, then rerun."
            )
        self._hold.start(self.hotkey)
        logger.info("hold %s to dictate", self.hotkey)

    def set_hotkey(self, name: str) -> None:
        chord = resolve_hotkey(name)
        spec = chord.spec()
        path = save_hotkey(config_path_for_write(self.cfg), spec)
        self.cfg = replace(
            self.cfg,
            path=path,
            input=replace(self.cfg.input, hotkey=spec),
        )
        self._hold.restart(spec)
        logger.info("shortcut set to %s (%s)", spec, chord.label())

    def pause_hotkey(self) -> None:
        self._hold.stop()

    def resume_hotkey(self) -> None:
        self._hold.start(self.hotkey)

    def update_llm(self, llm: LlmConfig) -> None:
        path = save_llm_config(config_path_for_write(self.cfg), llm)
        self.cfg = replace(self.cfg, path=path, llm=llm)
        logger.info(
            "llm settings saved refine=%s translate=%s model=%s",
            llm.refine.enabled,
            llm.translate.enabled,
            llm.model,
        )

    def shutdown(self) -> None:
        self._hold.stop()

        async def join() -> None:
            if self._stop is not None and not self._stop.is_set():
                self._stop.set()
            task = self._task
            if task is not None and not task.done():
                try:
                    await asyncio.wait_for(task, timeout=8)
                except Exception:
                    task.cancel()

        try:
            if self.loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(join(), self.loop)
                fut.result(timeout=9)
        except Exception:
            logger.debug("session did not finish on shutdown", exc_info=True)
        self._set_listening(False)

    def _on_press(self) -> None:
        self.loop.call_soon_threadsafe(self._start_session)

    def _on_release(self) -> None:
        self.loop.call_soon_threadsafe(self._stop_session)

    def _start_session(self) -> None:
        if self._task is not None and not self._task.done():
            return
        logger.info("listening (release %s to stop)", self.hotkey)
        if self.cfg.input.beep:
            beep()
        self._stop = asyncio.Event()
        self._set_listening(True)
        self._task = self.loop.create_task(self._run_session(), name="yark-session")

    def _stop_session(self) -> None:
        if self._stop is not None and not self._stop.is_set():
            logger.info("stopping")
            self._stop.set()

    async def _run_session(self) -> None:
        assert self._stop is not None
        try:
            pieces: list[str] = []
            pipeline = LlmPipeline(self.cfg.llm)
            async for piece in transcribe_until(self.cfg, self._stop):
                if pipeline.enabled():
                    pieces.append(piece)
                else:
                    inject_text(piece, self.mode)
            if pieces:
                raw = "".join(pieces)
                text = await asyncio.to_thread(pipeline.apply, raw)
                inject_text(text, self.mode)
            if self.mode == "print":
                print(flush=True)
            if self.cfg.input.beep:
                beep()
        except Exception:
            logger.exception("dictation session failed")
            if self.cfg.input.beep:
                beep()
        finally:
            self._set_listening(False)

    def _set_listening(self, listening: bool) -> None:
        try:
            self.on_listening(listening)
        except Exception:
            logger.debug("on_listening failed", exc_info=True)


def run_listener(cfg: AppConfig, *, inject_mode: str | None = None) -> None:
    mode = inject_mode or cfg.input.inject
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True, name="yark-asyncio")
    thread.start()
    runtime = DictationRuntime(cfg, mode, loop)
    try:
        if sys.platform == "darwin":
            from yark.statusbar import run_status_app

            run_status_app(runtime)
        else:
            _run_headless(runtime)
    finally:
        runtime.shutdown()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)


def _run_headless(runtime: DictationRuntime) -> None:
    runtime.start()
    print(
        f"yark is running. Hold {runtime.hotkey} to dictate, Ctrl+C to quit.",
        flush=True,
    )
    stop = threading.Event()

    def _sigint(*_args) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)
    try:
        while not stop.wait(0.25):
            pass
    finally:
        print("\nyark stopped.", flush=True)
