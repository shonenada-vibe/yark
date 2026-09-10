"""Hold-to-talk global hotkey, including modifier chords."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pynput import keyboard

from yark.errors import ConfigError

# macOS virtual key codes (HIToolbox Events.h)
_KEYCODE_TO_NAME: dict[int, str] = {
    0x3D: "right_option",
    0x3A: "left_option",
    0x36: "right_command",
    0x37: "left_command",
    0x3E: "right_control",
    0x3B: "left_control",
    0x3C: "right_shift",
    0x38: "left_shift",
    0x31: "space",
    0x64: "f8",
    0x65: "f9",
    0x69: "f13",
    0x6B: "f14",
    0x71: "f15",
    0x6A: "f16",
    0x40: "f17",
    0x4F: "f18",
    0x50: "f19",
}

ESCAPE_KEYCODE = 0x35

_ALIASES = {
    "cmd": "command",
    "alt": "option",
    "opt": "option",
    "ctrl": "control",
}

_FAMILY = {
    "command": "command",
    "cmd": "command",
    "left_command": "command",
    "right_command": "command",
    "option": "option",
    "alt": "option",
    "opt": "option",
    "left_option": "option",
    "right_option": "option",
    "control": "control",
    "ctrl": "control",
    "left_control": "control",
    "right_control": "control",
    "shift": "shift",
    "left_shift": "shift",
    "right_shift": "shift",
}

_MOD_RANK = {"command": 0, "option": 1, "control": 2, "shift": 3}

_SYMBOLS = {
    "command": "⌘",
    "option": "⌥",
    "control": "⌃",
    "shift": "⇧",
    "right_option": "Right ⌥",
    "left_option": "Left ⌥",
    "right_command": "Right ⌘",
    "left_command": "Left ⌘",
    "right_control": "Right ⌃",
    "left_control": "Left ⌃",
    "right_shift": "Right ⇧",
    "left_shift": "Left ⇧",
    "space": "Space",
}

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

_FAMILIES: dict[str, frozenset] = {
    "command": frozenset(
        {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r}
    ),
    "option": frozenset({keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}),
    "control": frozenset(
        {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
    ),
    "shift": frozenset(
        {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
    ),
}


def normalize_hotkey_name(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def canonicalize_part(name: str) -> str:
    key = normalize_hotkey_name(name)
    key = _ALIASES.get(key, key)
    return _FAMILY.get(key, key)


def recording_token_from_keycode(code: int) -> str | None:
    name = hotkey_from_keycode(code)
    if name is None:
        return None
    return canonicalize_part(name)


def hotkey_from_keycode(code: int) -> str | None:
    return _KEYCODE_TO_NAME.get(int(code))


def format_chord(parts: Iterable[str]) -> str:
    return parse_hotkey("+".join(parts)).spec()


@dataclass(frozen=True)
class HotkeyChord:
    parts: tuple[str, ...]

    def spec(self) -> str:
        return "+".join(self.parts)

    def label(self) -> str:
        bits = []
        for part in self.parts:
            if part in _SYMBOLS:
                bits.append(_SYMBOLS[part])
            elif part in _NAMED_KEYS and part.startswith("f") and part[1:].isdigit():
                bits.append(part.upper())
            elif len(part) == 1:
                bits.append(part.upper())
            else:
                bits.append(part.replace("_", " ").title())
        return " + ".join(bits)

    def matches(self, pressed: set) -> bool:
        if not self.parts:
            return False
        return all(not pressed.isdisjoint(_keys_for_part(part)) for part in self.parts)


def parse_hotkey(spec: str) -> HotkeyChord:
    raw = [normalize_hotkey_name(p) for p in re.split(r"[+\s]+", spec.strip()) if p]
    if not raw:
        raise ConfigError("empty shortcut")
    parts = [_ALIASES.get(p, p) for p in raw]
    for part in parts:
        if part == "fn":
            raise ConfigError(
                "fn is not a reliable hotkey; record Command+Option, F8, or similar"
            )
        if part not in _NAMED_KEYS and part not in _FAMILIES and len(part) != 1:
            raise ConfigError(f"unknown hotkey part {part!r} in {spec!r}")
    unique = list(dict.fromkeys(parts))
    unique.sort(key=lambda p: (_MOD_RANK.get(p, 100), p))
    return HotkeyChord(tuple(unique))


def hotkey_label(name: str) -> str:
    try:
        return parse_hotkey(name).label()
    except ConfigError:
        return name


def resolve_hotkey(name: str) -> HotkeyChord:
    return parse_hotkey(name)


def _keys_for_part(part: str) -> frozenset:
    if part in _FAMILIES:
        return _FAMILIES[part]
    if part in _NAMED_KEYS:
        key = _NAMED_KEYS[part]
        for family in _FAMILIES.values():
            if key in family:
                return frozenset({key})
        return frozenset({key})
    if len(part) == 1:
        return frozenset({keyboard.KeyCode.from_char(part)})
    return frozenset()


def _forget_key(pressed: set, key) -> None:
    pressed.discard(key)
    for family in _FAMILIES.values():
        if key in family:
            pressed.difference_update(family)
            return


class HoldListener:
    """Restartable hold-to-talk listener. Supports chords such as command+option."""

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ):
        self._on_press = on_press
        self._on_release = on_release
        self._listener: keyboard.Listener | None = None
        self._held = False

    def start(self, hotkey_name: str) -> None:
        self.stop()
        chord = parse_hotkey(hotkey_name)
        pressed: set = set()

        def _sync() -> None:
            active = chord.matches(pressed)
            if active and not self._held:
                self._held = True
                self._on_press()
            elif not active and self._held:
                self._held = False
                self._on_release()

        def _press(key) -> None:
            pressed.add(key)
            _sync()

        def _release(key) -> None:
            _forget_key(pressed, key)
            _sync()

        self._listener = keyboard.Listener(on_press=_press, on_release=_release)
        self._listener.start()

    def restart(self, hotkey_name: str) -> None:
        self.start(hotkey_name)

    def stop(self) -> None:
        if self._held:
            self._held = False
            try:
                self._on_release()
            except Exception:
                pass
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()


def start_hold_listener(
    hotkey_name: str,
    *,
    on_press: Callable[[], None],
    on_release: Callable[[], None],
) -> HoldListener:
    listener = HoldListener(on_press, on_release)
    listener.start(hotkey_name)
    return listener
