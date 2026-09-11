import pytest

from yark.errors import ConfigError
from yark.hotkey import (
    HoldMachine,
    expand_tokens,
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
    assert chord.matches_tokens(expand_tokens({"left_command", "right_option"}))
    assert chord.matches_tokens(expand_tokens({"right_command", "left_option"}))
    assert not chord.matches_tokens(expand_tokens({"left_command"}))
    assert not chord.matches_tokens(expand_tokens({"left_option"}))
    assert not chord.matches_tokens(set())


def test_right_option_does_not_match_left():
    chord = parse_hotkey("right_option")
    assert chord.matches_tokens(expand_tokens({"right_option"}))
    assert not chord.matches_tokens(expand_tokens({"left_option"}))
    assert parse_hotkey("option").matches_tokens(expand_tokens({"right_option"}))
    assert parse_hotkey("option").matches_tokens(expand_tokens({"left_option"}))


def test_select_mode_prefers_longer_chord():
    chords = {
        "transcript": parse_hotkey("option"),
        "translate": parse_hotkey("command+option"),
        "refine": parse_hotkey("command+shift+option"),
    }
    pressed = expand_tokens({"left_command", "left_option"})
    assert select_mode(pressed, chords) == "translate"
    pressed |= expand_tokens({"left_shift"})
    assert select_mode(pressed, chords) == "refine"
    assert select_mode(expand_tokens({"right_option"}), chords) == "transcript"
    assert select_mode(set(), chords) is None


def test_hold_machine_press_and_release():
    events: list = []
    machine = HoldMachine(
        lambda mode: events.append(("down", mode)),
        lambda: events.append("up"),
    )
    machine.set_chords(
        {
            "transcript": "right_option",
            "translate": "command+option",
        }
    )
    machine.sync(expand_tokens({"right_option"}))
    assert events == [("down", "transcript")]
    machine.sync(set())
    assert events == [("down", "transcript"), "up"]


def test_hold_machine_picks_translate_when_command_is_down_first():
    events: list = []
    machine = HoldMachine(
        lambda mode: events.append(("down", mode)),
        lambda: events.append("up"),
    )
    machine.set_chords(
        {
            "transcript": "option",
            "translate": "command+option",
        }
    )
    machine.sync(expand_tokens({"left_command"}))
    assert events == []
    machine.sync(expand_tokens({"left_command", "left_option"}))
    assert events == [("down", "translate")]
    machine.sync(expand_tokens({"left_option"}))
    assert events == [("down", "translate"), "up"]
