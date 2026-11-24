import os
import subprocess
import sys
import threading

from yark import winbridge
from yark.hotkey import parse_hotkey
from yark.winbridge import host_script_path, parse_keys_line, running_in_wsl


def test_parse_keys_line():
    assert parse_keys_line("YARK keys") == set()
    tokens = parse_keys_line("YARK keys right_option")
    assert tokens is not None
    assert "right_option" in tokens
    assert "option" in tokens
    assert parse_keys_line("ready") is None


def test_windows_chords_match_macos_config_names():
    chord = parse_hotkey("command+option")
    tokens = parse_keys_line("YARK keys left_command right_option")
    assert tokens is not None
    assert chord.matches_tokens(tokens)
    assert parse_hotkey("right_option").matches_tokens(
        parse_keys_line("YARK keys right_option")
    )
    assert not parse_hotkey("right_option").matches_tokens(
        parse_keys_line("YARK keys left_option")
    )


def test_host_script_ships_with_package():
    path = host_script_path()
    text = path.read_text(encoding="utf-8")
    assert "YARK keys" in text
    assert "YARK pcm" in text
    assert "GetAsyncKeyState" in text
    assert "YARK tray ready" in text


def test_windows_tray_sends_recording_state_and_handles_exit(monkeypatch):
    helper = """
import sys

print('YARK tray ready', flush=True)
assert sys.stdin.readline().strip() == 'listening'
assert sys.stdin.readline().strip() == 'ready'
print('YARK tray quit', flush=True)
assert not sys.stdin.read()
"""
    start_process = subprocess.Popen

    def start_tray(command, **kwargs):
        assert command[-2:] == ["-Mode", "tray"]
        return start_process([sys.executable, "-c", helper], **kwargs)

    monkeypatch.setattr(winbridge, "_powershell_base", lambda: ["powershell.exe"])
    monkeypatch.setattr(winbridge, "windows_path", str)
    monkeypatch.setattr(winbridge.subprocess, "Popen", start_tray)
    quit_requested = threading.Event()
    tray = winbridge.WinTray(quit_requested.set)
    tray.start()
    try:
        tray.set_listening(True)
        tray.set_listening(False)
        assert quit_requested.wait(timeout=2)
    finally:
        tray.stop()


def test_running_in_wsl_false_outside_wsl(monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    monkeypatch.setattr("yark.winbridge.sys.platform", "darwin")
    assert running_in_wsl() is False


def test_wsl_falls_back_to_windows_microphone_without_portaudio(tmp_path):
    config = tmp_path / "config.toml"
    config.touch()
    script = """
import sys

class MissingPortAudio:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "sounddevice":
            raise OSError("PortAudio library not found")

sys.meta_path.insert(0, MissingPortAudio())

from yark.cli import main

main(["-c", sys.argv[1], "wsl", "--doctor"])

from yark.winbridge import WinMicrophone, open_microphone

assert isinstance(open_microphone(16000, 100), WinMicrophone)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(config)],
        env={**os.environ, "WSL_DISTRO_NAME": "test"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "linux mic: no (will use Windows recording device)" in result.stdout
