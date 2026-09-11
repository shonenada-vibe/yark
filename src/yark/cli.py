from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from yark import __version__
from yark.config import AppConfig, load_config, write_example_config
from yark.errors import ConfigError, YarkError
from yark.inject import inject_text
from yark.mic import list_input_devices
from yark.permissions import check_accessibility, check_microphone


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        args.handler(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        sys.exit(2)
    except YarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yark",
        description="macOS voice-to-text input (Volcengine streaming ASR)",
    )
    parser.add_argument("--version", action="version", version=f"yark {__version__}")
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="config.toml path (default: ./config.toml or ~/.config/yark/config.toml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    listen = sub.add_parser("listen", help="hold-to-talk and type into the focused app")
    listen.add_argument("--print", dest="print_only", action="store_true", help="print instead of typing")
    listen.add_argument("--hotkey", help="override hold-to-talk key")
    listen.set_defaults(handler=_cmd_listen)

    once = sub.add_parser("once", help="record until Enter, then print / type the result")
    once.add_argument("--print", dest="print_only", action="store_true")
    once.set_defaults(handler=_cmd_once)

    doctor = sub.add_parser("doctor", help="check config, mic, and macOS permissions")
    doctor.set_defaults(handler=_cmd_doctor)

    init = sub.add_parser("init-config", help="write ~/.config/yark/config.toml")
    init.set_defaults(handler=_cmd_init)

    parser.set_defaults(handler=_cmd_listen, print_only=False, hotkey=None, command="listen")
    return parser


def _load(args) -> AppConfig:
    return load_config(args.config)


def _require_auth(cfg: AppConfig) -> None:
    cfg.volcengine.auth_headers("probe")


def _cmd_listen(args) -> None:
    from dataclasses import replace

    from yark.app import run_listener

    cfg = _load(args)
    _require_auth(cfg)
    if args.hotkey:
        cfg = replace(cfg, input=replace(cfg.input, hotkey=args.hotkey))
    mode = "print" if args.print_only else cfg.input.inject
    run_listener(cfg, inject_mode=mode)


def _cmd_once(args) -> None:
    cfg = _load(args)
    _require_auth(cfg)
    mode = "print" if args.print_only else cfg.input.inject
    asyncio.run(_once(cfg, mode))


async def _once(cfg: AppConfig, mode: str) -> None:
    from yark.session import transcribe_until

    stop = asyncio.Event()
    print("Recording. Press Enter to stop.", flush=True)

    async def wait_enter() -> None:
        await asyncio.to_thread(sys.stdin.readline)
        stop.set()

    waiter = asyncio.create_task(wait_enter())
    texts: list[str] = []
    try:
        from yark.llm import LlmPipeline

        pipeline = LlmPipeline(cfg.llm)
        buffered: list[str] = []
        async for piece in transcribe_until(cfg, stop):
            if pipeline.enabled():
                buffered.append(piece)
            else:
                texts.append(piece)
                if mode == "print":
                    print(piece, end="", flush=True)
                else:
                    inject_text(piece, mode)
        if buffered:
            text = pipeline.apply("".join(buffered))
            texts.append(text)
            if mode == "print":
                print(text, end="", flush=True)
            else:
                inject_text(text, mode)
    finally:
        stop.set()
        waiter.cancel()
    if mode == "print":
        print(flush=True)
    if not texts:
        print("(no speech recognized)", file=sys.stderr)


def _cmd_doctor(args) -> None:
    cfg = _load(args)
    print(f"yark {__version__}")
    print(f"config: {cfg.path or '(defaults + env)'}")
    print(f"volcengine: {cfg.volcengine.redacted()}")
    print(f"endpoint: {cfg.volcengine.endpoint}")
    print(f"hotkey: {cfg.input.hotkey}")
    print(f"inject: {cfg.input.inject}")
    print(
        f"llm: model={cfg.llm.model} refine={'on' if cfg.llm.refine.enabled else 'off'} "
        f"translate={'on' if cfg.llm.translate.enabled else 'off'}"
    )
    try:
        cfg.volcengine.auth_headers("doctor")
        print("auth: ok")
    except ConfigError as exc:
        print(f"auth: MISSING ({exc})")
    print("microphone permission:", "ok" if check_microphone() else "not granted / unknown")
    print("accessibility permission:", "ok" if check_accessibility(prompt=False) else "not granted")
    print("input devices:")
    try:
        for row in list_input_devices():
            print(f"  {row}")
    except Exception as exc:
        print(f"  (cannot list devices: {exc})")


def _cmd_init(args) -> None:
    path = args.config or (Path.home() / ".config" / "yark" / "config.toml")
    if path.exists():
        print(f"already exists: {path}")
        return
    write_example_config(path)
    print(f"wrote {path}")
    print("Fill in volcengine.api_key, then run: yark doctor && yark listen")
