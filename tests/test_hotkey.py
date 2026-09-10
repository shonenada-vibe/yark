import pytest
from pynput import keyboard

from yark.errors import ConfigError
from yark.hotkey import resolve_hotkey


def test_named_hotkeys():
    assert resolve_hotkey("right_option") == keyboard.Key.alt_r
    assert resolve_hotkey("F8") == keyboard.Key.f8
    assert resolve_hotkey("right-command") == keyboard.Key.cmd_r


def test_unknown_hotkey():
    with pytest.raises(ConfigError):
        resolve_hotkey("fn")
    with pytest.raises(ConfigError):
        resolve_hotkey("not-a-key")
