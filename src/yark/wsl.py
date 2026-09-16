"""Windows/WSL hold-to-talk runtime.

Python (and Volcengine STT) run in WSL. A PowerShell helper on the Windows
side watches hold-to-talk keys and types into the focused Windows app.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from yark import __version__
from yark.config import AppConfig, load_config
from yark.errors import ConfigError, YarkError, format_hud_error
from yark.llm import LlmPipeline
from yark.session import transcribe_until
from yark.winbridge import (
    WinHoldListener,
    beep,
    doctor_lines,
    inject_text,
    on_windows_host,
    open_microphone,
    running_in_wsl,
)

logger = logging.getLogger("yark.wsl")


class WslRuntime:
    """Hold-to-talk sessions without AppKit."""

    def __init__(self, cfg: AppConfig, inject_mode: str, loop: asyncio.AbstractEventLoop):
        self.cfg = cfg
        self.mode = inject_mode
        self.loop = loop
        self.on_listening: Callable[[bool], None] = lambda _listening: None
        self.on_error: Callable[[str], None] = lambda _message: None
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._session_mode = "transcript"
        self._hold = WinHoldListener(self._on_press, self._on_release)

    @property
    def session_mode(self) -> str:
        return self._session_mode

    def start(self) -> None:
        mapping = self.cfg.input.hotkey_map()
        self._hold.start(mapping)
        logger.info("hold shortcuts %s (option=Alt, command=Win, control=Ctrl)", mapping)

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

    def _on_press(self, mode: str) -> None:
        self.loop.call_soon_threadsafe(self._start_session, mode)

    def _on_release(self) -> None:
        self.loop.call_soon_threadsafe(self._stop_session)

    def _start_session(self, mode: str = "transcript") -> None:
        if self._task is not None and not self._task.done():
            return
        self._session_mode = mode
        logger.info("listening mode=%s", mode)
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
        failed: BaseException | None = None
        llm_error: BaseException | None = None
        llm_action: str | None = None
        audio = self.cfg.audio
        microphone = open_microphone(audio.sample_rate, audio.chunk_ms, audio.device)
        try:
            pieces: list[str] = []
            pipeline = LlmPipeline(self.cfg.llm)
            dictation_mode = self._session_mode
            async for piece in transcribe_until(
                self.cfg, self._stop, microphone=microphone
            ):
                if pipeline.enabled(dictation_mode):
                    pieces.append(piece)
                else:
                    inject_text(piece, self.mode)
            if pieces:
                raw = "".join(pieces)
                text = await asyncio.to_thread(pipeline.apply, raw, dictation_mode)
                llm_error = pipeline.last_error
                llm_action = pipeline.last_error_action
                inject_text(text, self.mode)
            if self.mode == "print":
                print(flush=True)
            if self.cfg.input.beep:
                beep()
        except Exception as exc:
            failed = exc
            logger.exception("dictation session failed")
            if self.cfg.input.beep:
                beep()
        finally:
            self._set_listening(False)
        if failed is not None:
            self._notify_error(failed)
        elif llm_error is not None:
            self._notify_error(llm_error, action=llm_action)

    def _set_listening(self, listening: bool) -> None:
        try:
            self.on_listening(listening)
        except Exception:
            logger.debug("on_listening failed", exc_info=True)

    def _notify_error(self, exc: BaseException, *, action: str | None = None) -> None:
        message = format_hud_error(exc, action=action)
        try:
            self.on_error(message)
        except Exception:
            logger.debug("on_error failed", exc_info=True)


def run_wsl_listener(cfg: AppConfig, *, inject_mode: str | None = None) -> None:
    if not on_windows_host():
        raise YarkError(
            "yark wsl needs WSL or Windows. On macOS run: yark listen"
        )
    mode = inject_mode or cfg.input.inject
    if mode == "unicode":
        logger.info("Windows/WSL types via clipboard paste (Ctrl+V)")
        mode = "paste"
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True, name="yark-asyncio")
    thread.start()
    runtime = WslRuntime(cfg, mode, loop)
    runtime.on_listening = _print_listening
    runtime.on_error = _print_error
    try:
        runtime.start()
        print(
            f"yark wsl is running. Shortcuts: {runtime.cfg.input.hotkey_map()}. "
            "option=Alt, command=Win, control=Ctrl. Ctrl+C to quit.",
            flush=True,
        )
        _wait_for_stop()
    finally:
        runtime.shutdown()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        print("\nyark stopped.", flush=True)


def _print_listening(listening: bool) -> None:
    if listening:
        print("Listening…", flush=True)
    else:
        print("Ready", flush=True)


def _print_error(message: str) -> None:
    print(f"yark: {message}", file=sys.stderr, flush=True)


def _wait_for_stop() -> None:
    stop = threading.Event()

    def _sigint(*_args) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)
    while not stop.wait(0.25):
        pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="yark-wsl",
        description="Hold-to-talk voice input for Windows, run from WSL",
    )
    parser.add_argument("--version", action="version", version=f"yark {__version__}")
    parser.add_argument("-c", "--config", type=Path)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--print", dest="print_only", action="store_true")
    parser.add_argument("--hotkey", help="override transcript hold-to-talk key")
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="check WSL/Windows bridge instead of listening",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.doctor:
            _print_doctor(load_config(args.config))
            return
        cfg = load_config(args.config)
        cfg.volcengine.auth_headers("probe")
        if args.hotkey:
            cfg = replace(
                cfg,
                input=replace(
                    cfg.input, hotkey=args.hotkey, hotkey_transcript=args.hotkey
                ),
            )
        mode = "print" if args.print_only else cfg.input.inject
        run_wsl_listener(cfg, inject_mode=mode)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        sys.exit(2)
    except YarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def _print_doctor(cfg: AppConfig | None = None) -> None:
    print(f"yark {__version__} ({'WSL' if running_in_wsl() else sys.platform})")
    if cfg is not None:
        print(f"config: {cfg.path or '(defaults + env)'}")
        print(f"hotkeys: {cfg.input.hotkey_map()}")
    for line in doctor_lines():
        print(line)


if __name__ == "__main__":
    main()
