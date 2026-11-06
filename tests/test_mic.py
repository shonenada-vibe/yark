import asyncio
from unittest.mock import Mock

import pytest
import sounddevice as sd

from yark.config import AudioConfig
from yark.errors import YarkError
from yark.mic import Microphone, list_input_devices


def test_open_error_reports_device_and_settings_without_diagnosing_permission(monkeypatch):
    error = sd.PortAudioError("Error opening InputStream: Internal PortAudio error", -9986)
    monkeypatch.setattr("yark.mic.sd.InputStream", Mock(side_effect=error))

    with pytest.raises(YarkError) as raised:
        asyncio.run(Microphone(AudioConfig(device="2")).start())

    message = str(raised.value)
    assert "-9986" in message
    assert "device=2" in message
    assert "16000 Hz" in message
    assert "doctor --test-mic" in message
    assert "Grant Microphone permission" not in message
    assert raised.value.__cause__ is error


def test_failed_start_closes_stream_and_leaves_microphone_stopped(monkeypatch):
    stream = Mock()
    stream.start.side_effect = sd.PortAudioError("Error starting stream", -9986)
    monkeypatch.setattr("yark.mic.sd.InputStream", Mock(return_value=stream))
    mic = Microphone(AudioConfig())

    async def run():
        with pytest.raises(YarkError, match="cannot open microphone"):
            await mic.start()
        with pytest.raises(YarkError, match="microphone is not started"):
            await asyncio.wait_for(anext(mic.chunks()), timeout=0.1)
        await mic.stop()

    asyncio.run(run())
    stream.close.assert_called_once()


def test_stop_closes_stream_even_when_stop_fails(monkeypatch):
    stream = Mock()
    stream.stop.side_effect = sd.PortAudioError("Error stopping stream", -9986)
    monkeypatch.setattr("yark.mic.sd.InputStream", Mock(return_value=stream))

    async def run():
        async with Microphone(AudioConfig()):
            pass

    asyncio.run(run())
    stream.close.assert_called_once()


def test_input_devices_marks_sounddevice_default_pair(monkeypatch):
    # sounddevice uses an indexable _InputOutputPair, not a list or tuple.
    class DevicePair:
        def __getitem__(self, index):
            return (2, 0)[index]

    monkeypatch.setattr("yark.mic.sd.default", Mock(device=DevicePair()))
    monkeypatch.setattr("yark.mic.sd.query_devices", lambda: [
        {"name": "Speakers", "max_input_channels": 0},
        {"name": "USB Mic", "max_input_channels": 1},
        {"name": "Built-in Mic", "max_input_channels": 1},
    ])

    assert list_input_devices() == ["1: USB Mic", "2: Built-in Mic (default)"]
