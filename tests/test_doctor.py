from unittest.mock import Mock

import numpy as np
import pytest
import sounddevice as sd

from yark import cli
from yark.config import AppConfig, AudioConfig


@pytest.fixture
def doctor(monkeypatch):
    cfg = AppConfig(audio=AudioConfig(sample_rate=16000, chunk_ms=200, device="2"))
    monkeypatch.setattr(cli, "_load", lambda _args: cfg)
    monkeypatch.setattr(cli, "check_microphone", lambda: True)
    monkeypatch.setattr(cli, "check_accessibility", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "list_input_devices", lambda: ["2: Test Mic (default)"])
    monkeypatch.setattr("yark.winbridge.on_windows_host", lambda: False)
    return cfg


def test_doctor_does_not_capture_without_test_flag(doctor, monkeypatch, capsys):
    factory = Mock(side_effect=AssertionError("unexpected capture"))
    monkeypatch.setattr("yark.mic.sd.InputStream", factory)

    cli.main(["doctor"])

    factory.assert_not_called()
    assert "2: Test Mic (default)" in capsys.readouterr().out


def test_doctor_tests_configured_microphone_without_auth(doctor, monkeypatch, capsys):
    stream = Mock()

    def open_stream(**kwargs):
        assert kwargs["device"] == 2
        assert kwargs["samplerate"] == doctor.audio.sample_rate
        frames = kwargs["blocksize"]
        pcm = np.zeros((frames, 1), dtype=np.int16)
        stream.start.side_effect = lambda: kwargs["callback"](pcm, frames, None, None)
        return stream

    monkeypatch.setattr("yark.mic.sd.InputStream", open_stream)

    cli.main(["doctor", "--test-mic"])

    output = capsys.readouterr().out
    assert "auth: MISSING" in output
    assert "microphone capture: ok (6400 PCM bytes received and discarded)" in output
    stream.close.assert_called_once()


def test_doctor_returns_failure_when_microphone_cannot_open(doctor, monkeypatch, capsys):
    error = sd.PortAudioError("Error opening InputStream: Internal PortAudio error", -9986)
    monkeypatch.setattr("yark.mic.sd.InputStream", Mock(side_effect=error))

    with pytest.raises(SystemExit) as raised:
        cli.main(["doctor", "--test-mic"])

    assert raised.value.code == 1
    output = capsys.readouterr()
    assert "-9986" in output.err
    assert "device=2" in output.err
    assert "microphone capture: ok" not in output.out


def test_doctor_closes_microphone_when_no_audio_arrives(doctor, monkeypatch, capsys):
    stream = Mock()
    monkeypatch.setattr("yark.mic.sd.InputStream", Mock(return_value=stream))
    wait_for = cli.asyncio.wait_for

    async def short_wait(awaitable, timeout):
        return await wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(cli.asyncio, "wait_for", short_wait)

    with pytest.raises(SystemExit) as raised:
        cli.main(["doctor", "--test-mic"])

    assert raised.value.code == 1
    assert "microphone opened but delivered no audio" in capsys.readouterr().err
    stream.close.assert_called_once()
