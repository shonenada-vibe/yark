import pytest
from pynput import keyboard

from yark.errors import ConfigError
from yark.hotkey import (
    hotkey_from_keycode,
    hotkey_label,
    normalize_hotkey_name,
    resolve_hotkey,
)


def test_named_hotkeys():
    assert resolve_hotkey("right_option") == keyboard.Key.alt_r
    assert resolve_hotkey("F8") == keyboard.Key.f8
    assert resolve_hotkey("right-command") == keyboard.Key.cmd_r


def test_unknown_hotkey():
    with pytest.raises(ConfigError):
        resolve_hotkey("fn")
    with pytest.raises(ConfigError):
        resolve_hotkey("not-a-key")


def test_hotkey_label_and_normalize():
    assert normalize_hotkey_name("Right-Option") == "right_option"
    assert hotkey_label("right_option") == "Right Option (⌥)"
    assert hotkey_label("f13") == "F13"


def test_keycode_mapping():
    assert hotkey_from_keycode(0x3D) == "right_option"
    assert hotkey_from_keycode(0x36) == "right_command"
    assert hotkey_from_keycode(0x64) == "f8"
    assert hotkey_from_keycode(0x35) is None
