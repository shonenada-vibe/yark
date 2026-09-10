"""Microphone capture: 16-bit little-endian PCM mono."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import numpy as np
import sounddevice as sd

from yark.config import AudioConfig
from yark.errors import YarkError

logger = logging.getLogger("yark.mic")
_SENTINEL = object()


class Microphone:
    def __init__(self, audio: AudioConfig):
        self._audio = audio
        self._queue: asyncio.Queue[object] | None = None
        self._stream: sd.InputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopped = False

    async def __aenter__(self) -> "Microphone":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=32)
        self._stopped = False
        blocksize = max(1, self._audio.sample_rate * self._audio.chunk_ms // 1000)
        device = _resolve_device(self._audio.device)
        logger.info(
            "mic start device=%s rate=%s chunk_ms=%s",
            device if device is not None else "default",
            self._audio.sample_rate,
            self._audio.chunk_ms,
        )
        try:
            self._stream = sd.InputStream(
                samplerate=self._audio.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=blocksize,
                device=device,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            raise YarkError(
                f"cannot open microphone: {exc}. Grant Microphone permission to "
                "the terminal / Python in System Settings → Privacy & Security."
            ) from exc

    async def chunks(self) -> AsyncIterator[bytes]:
        if self._queue is None:
            raise YarkError("microphone is not started")
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                return
            yield item  # type: ignore[misc]

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                logger.debug("mic stream close failed", exc_info=True)
        if self._queue is not None:
            try:
                self._queue.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                pass

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if status:
            logger.debug("mic status: %s", status)
        if self._loop is None or self._queue is None:
            return
        pcm = np.ascontiguousarray(indata, dtype=np.int16).tobytes()
        if not pcm:
            return

        def _put() -> None:
            assert self._queue is not None
            try:
                self._queue.put_nowait(pcm)
            except asyncio.QueueFull:
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self._queue.put_nowait(pcm)
                except asyncio.QueueFull:
                    pass

        self._loop.call_soon_threadsafe(_put)


def _resolve_device(name: str) -> int | None:
    if not name:
        return None
    try:
        return int(name)
    except ValueError:
        pass
    devices = sd.query_devices()
    lowered = name.lower()
    for index, info in enumerate(devices):
        if info.get("max_input_channels", 0) <= 0:
            continue
        if lowered in str(info.get("name", "")).lower():
            return index
    raise YarkError(f"microphone device not found: {name!r}")


def list_input_devices() -> list[str]:
    rows = []
    default = sd.default.device
    default_in = default[0] if isinstance(default, (list, tuple)) else default
    for index, info in enumerate(sd.query_devices()):
        if info.get("max_input_channels", 0) <= 0:
            continue
        mark = " (default)" if index == default_in else ""
        rows.append(f"{index}: {info.get('name')}{mark}")
    return rows
