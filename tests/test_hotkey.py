import pytest
from pynput import keyboard

from yark.errors import ConfigError
from yark.hotkey import (
    hotkey_from_keycode,
    hotkey_label,
    normalize_hotkey_name,
    parse_hotkey,
    recording_token_from_keycode,
    resolve_hotkey,
    select_mode,
)


def test_named_hotkeys():
    assert resolve_hotkey("right_option").spec() == "right_option"
    assert resolve_hotkey("F8").spec() == "f8"
    assert resolve_hotkey("right-command").spec() == "right_command"


def test_command_option_chord():
    chord = parse_hotkey("command+option")
    assert chord.spec() == "command+option"
    assert chord.label() == "⌘ + ⌥"
    assert parse_hotkey("cmd+alt").spec() == "command+option"
    assert parse_hotkey("option + command").spec() == "command+option"


def test_unknown_hotkey():
    with pytest.raises(ConfigError):
        resolve_hotkey("fn")
    with pytest.raises(ConfigError):
        resolve_hotkey("not-a-key")
    with pytest.raises(ConfigError):
        resolve_hotkey("command+nope")


def test_hotkey_label_and_normalize():
    assert normalize_hotkey_name("Right-Option") == "right_option"
    assert hotkey_label("right_option") == "Right ⌥"
    assert hotkey_label("f13") == "F13"
    assert hotkey_label("command+option") == "⌘ + ⌥"


def test_keycode_mapping():
    assert hotkey_from_keycode(0x3D) == "right_option"
    assert hotkey_from_keycode(0x36) == "right_command"
    assert hotkey_from_keycode(0x64) == "f8"
    assert hotkey_from_keycode(0x35) is None
    assert recording_token_from_keycode(0x3D) == "option"
    assert recording_token_from_keycode(0x36) == "command"


def test_chord_matches_any_side():
    chord = parse_hotkey("command+option")
    assert chord.matches({keyboard.Key.cmd_l, keyboard.Key.alt_r})
    assert chord.matches({keyboard.Key.cmd_r, keyboard.Key.alt_l})
    assert not chord.matches({keyboard.Key.cmd_l})
    assert not chord.matches({keyboard.Key.alt_l})
    assert not chord.matches(set())


def test_select_mode_prefers_longer_chord():
    chords = {
        "transcript": parse_hotkey("option"),
        "translate": parse_hotkey("command+option"),
        "refine": parse_hotkey("command+shift+option"),
    }
    pressed = {keyboard.Key.cmd_l, keyboard.Key.alt_l}
    assert select_mode(pressed, chords) == "translate"
    pressed.add(keyboard.Key.shift_l)
    assert select_mode(pressed, chords) == "refine"
    assert select_mode({keyboard.Key.alt_r}, chords) == "transcript"
    assert select_mode(set(), chords) is None
