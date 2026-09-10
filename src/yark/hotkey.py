"""Hold-to-talk global hotkey."""

from __future__ import annotations

from collections.abc import Callable

from pynput import keyboard

from yark.errors import ConfigError

_NAMED_KEYS: dict[str, keyboard.Key] = {
    "right_option": keyboard.Key.alt_r,
    "left_option": keyboard.Key.alt_l,
    "option": keyboard.Key.alt,
    "alt": keyboard.Key.alt,
    "right_command": keyboard.Key.cmd_r,
    "left_command": keyboard.Key.cmd_l,
    "command": keyboard.Key.cmd,
    "cmd": keyboard.Key.cmd,
    "right_control": keyboard.Key.ctrl_r,
    "left_control": keyboard.Key.ctrl_l,
    "control": keyboard.Key.ctrl,
    "ctrl": keyboard.Key.ctrl,
    "right_shift": keyboard.Key.shift_r,
    "left_shift": keyboard.Key.shift_l,
    "shift": keyboard.Key.shift,
    "fn": keyboard.Key.cmd,  # placeholder; fn is not reliably exposed
    "space": keyboard.Key.space,
    "f8": keyboard.Key.f8,
    "f9": keyboard.Key.f9,
    "f13": keyboard.Key.f13,
    "f14": keyboard.Key.f14,
    "f15": keyboard.Key.f15,
    "f16": keyboard.Key.f16,
    "f17": keyboard.Key.f17,
    "f18": keyboard.Key.f18,
    "f19": keyboard.Key.f19,
}


def resolve_hotkey(name: str):
    key = name.strip().lower().replace("-", "_").replace(" ", "_")
    if key in _NAMED_KEYS:
        if key == "fn":
            raise ConfigError(
                "fn is not a reliable hotkey via pynput; use right_option, "
                "right_command, f8, or f13"
            )
        return _NAMED_KEYS[key]
    if len(key) == 1:
        return keyboard.KeyCode.from_char(key)
    raise ConfigError(
        f"unknown hotkey {name!r}. Try right_option, right_command, f8, or f13"
    )


def start_hold_listener(
    hotkey_name: str,
    *,
    on_press: Callable[[], None],
    on_release: Callable[[], None],
) -> keyboard.Listener:
    target = resolve_hotkey(hotkey_name)
    held = False

    def _matches(key) -> bool:
        return key == target

    def _press(key) -> None:
        nonlocal held
        if held or not _matches(key):
            return
        held = True
        on_press()

    def _release(key) -> None:
        nonlocal held
        if not held or not _matches(key):
            return
        held = False
        on_release()

    listener = keyboard.Listener(on_press=_press, on_release=_release)
    listener.start()
    return listener
