import asyncio
from collections.abc import AsyncIterator

from yark.config import AppConfig
from yark.errors import SttError
from yark.protocol import ServerResponse
from yark.session import transcribe_until


class FakeMic:
    def __init__(self, *, chunk: bytes = b"\x00\x01", interval: float = 0.01, maxsize: int = 8):
        self.chunk = chunk
        self.interval = interval
        self.queue: asyncio.Queue[object] = asyncio.Queue(maxsize=maxsize)
        self.stopped = False
        self.stop_at: float | None = None
        self._producer: asyncio.Task | None = None

    async def __aenter__(self) -> "FakeMic":
        self._producer = asyncio.create_task(self._produce())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    async def _produce(self) -> None:
        try:
            while not self.stopped:
                try:
                    self.queue.put_nowait(self.chunk)
                except asyncio.QueueFull:
                    try:
                        self.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            return

    async def chunks(self) -> AsyncIterator[bytes]:
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item  # type: ignore[misc]

    async def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        self.stop_at = asyncio.get_running_loop().time()
        producer = self._producer
        self._producer = None
        if producer is not None and not producer.done():
            producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                pass
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass


class FakeStt:
    def __init__(self, *, connect_delay: float = 0.0, mic: FakeMic | None = None):
        self.connect_delay = connect_delay
        self.mic = mic
        self.sent: list[tuple[bytes, bool]] = []
        self.mic_stopped_during_connect = False
        self.entered_at: float | None = None

    async def __aenter__(self) -> "FakeStt":
        await asyncio.sleep(self.connect_delay)
        self.entered_at = asyncio.get_running_loop().time()
        if self.mic is not None:
            self.mic_stopped_during_connect = self.mic.stopped
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def send_audio(self, pcm: bytes, *, last: bool = False) -> None:
        self.sent.append((pcm, last))

    async def responses(self) -> AsyncIterator[ServerResponse]:
        deadline = asyncio.get_running_loop().time() + 1.0
        while asyncio.get_running_loop().time() < deadline:
            if any(last for _, last in self.sent):
                yield ServerResponse(
                    is_last_package=True,
                    payload_msg={
                        "result": {
                            "text": "hello",
                            "utterances": [
                                {"definite": True, "start_time": 0, "text": "hello"}
                            ],
                        }
                    },
                )
                return
            await asyncio.sleep(0.01)
        raise SttError(
            "ASR error code=45000081 payload={'error': "
            "'Timed out waiting for the next audio packet.'}"
        )


def test_stop_during_slow_connect_sends_last_packet():
    async def run() -> tuple[list[str], FakeStt, FakeMic]:
        mic = FakeMic()
        stt = FakeStt(connect_delay=0.25, mic=mic)
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(0.05, stop.set)
        pieces = [
            piece
            async for piece in transcribe_until(
                AppConfig(), stop, microphone=mic, stt=stt
            )
        ]
        return pieces, stt, mic

    pieces, stt, mic = asyncio.run(asyncio.wait_for(run(), timeout=2))
    assert mic.stopped is True
    assert stt.mic_stopped_during_connect is True
    assert any(last for _, last in stt.sent)
    assert pieces == ["hello"]
