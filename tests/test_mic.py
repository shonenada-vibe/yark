import asyncio

from yark.config import AudioConfig
from yark.mic import Microphone, put_queue_end


def test_put_queue_end_makes_room_when_full():
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=2)
    queue.put_nowait(b"old")
    queue.put_nowait(b"new")
    marker = object()
    put_queue_end(queue, marker)
    assert queue.qsize() == 2
    assert marker in {queue.get_nowait(), queue.get_nowait()}



def test_stop_unblocks_chunks_when_queue_is_full():
    async def run() -> list[bytes]:
        mic = Microphone(AudioConfig())
        mic._queue = asyncio.Queue(maxsize=2)
        mic._loop = asyncio.get_running_loop()
        assert mic._queue is not None
        mic._queue.put_nowait(b"a")
        mic._queue.put_nowait(b"b")
        await mic.stop()
        out: list[bytes] = []
        async for chunk in mic.chunks():
            out.append(chunk)
        return out

    chunks = asyncio.run(asyncio.wait_for(run(), timeout=1))
    assert b"a" in chunks or b"b" in chunks
    assert len(chunks) <= 2
