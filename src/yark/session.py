"""One dictation session: mic → Volcengine STT → committed text."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable

from yark.config import AppConfig
from yark.mic import Microphone
from yark.stt import VolcengineStt
from yark.transcript import TranscriptCommitter

logger = logging.getLogger("yark.session")


async def transcribe_until(
    cfg: AppConfig,
    stop: asyncio.Event,
    *,
    on_partial: Callable[[str], None] | None = None,
) -> AsyncIterator[str]:
    """Yield committed phrases until `stop` is set and the server finishes."""
    committer = TranscriptCommitter()
    async with Microphone(cfg.audio) as mic, VolcengineStt(cfg) as stt:
        watcher = asyncio.create_task(_stop_mic_when(stop, mic), name="yark-stop-mic")
        send_task = asyncio.create_task(_pump_audio(mic, stt), name="yark-send")
        try:
            async for response in stt.responses():
                if on_partial:
                    text = response.text()
                    if text:
                        on_partial(text)
                for piece in committer.feed(response):
                    logger.info("commit %r", piece)
                    yield piece
        finally:
            if not stop.is_set():
                stop.set()
            for task in (watcher, send_task):
                if not task.done():
                    task.cancel()
            for task in (watcher, send_task):
                try:
                    await task
                except asyncio.CancelledError:
                    pass


async def _stop_mic_when(stop: asyncio.Event, mic: Microphone) -> None:
    await stop.wait()
    await mic.stop()


async def _pump_audio(mic: Microphone, stt: VolcengineStt) -> None:
    pending = b""
    sent_last = False

    async def send_last() -> None:
        nonlocal sent_last
        if sent_last:
            return
        sent_last = True
        await stt.send_audio(pending, last=True)

    try:
        async for chunk in mic.chunks():
            if pending:
                await stt.send_audio(pending, last=False)
            pending = chunk
        await send_last()
    except asyncio.CancelledError:
        try:
            await send_last()
        except Exception:
            logger.debug("failed to send last audio packet", exc_info=True)
        raise
