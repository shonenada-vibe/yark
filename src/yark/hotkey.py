"""Hold-to-talk global hotkey, including modifier chords.

macOS 26+ asserts that HIToolbox TSM APIs run on the main queue.
pynput's keyboard listener calls TSMGetInputSourceProperty on a
background thread, which aborts the process (EXC_BREAKPOINT) as soon as
a shortcut is applied and the listener restarts. Hold-to-talk therefore
uses NSEvent monitors on the AppKit main thread.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from yark.errors import ConfigError

logger = logging.getLogger("yark.hotkey")

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

_NAMED = {
    "right_option",
    "left_option",
    "option",
    "right_command",
    "left_command",
    "command",
    "right_control",
    "left_control",
    "control",
    "right_shift",
    "left_shift",
    "shift",
    "space",
    "f8",
    "f9",
    "f13",
    "f14",
    "f15",
    "f16",
    "f17",
    "f18",
    "f19",
}

_FAMILIES = frozenset({"command", "option", "control", "shift"})

# NX_DEVICE*KEYMASK bits in NSEvent.modifierFlags (IOLLEvent.h)
_DEVICE_BITS = {
    "left_command": 0x00000008,
    "right_command": 0x00000010,
    "left_shift": 0x00000002,
    "right_shift": 0x00000004,
    "left_option": 0x00000020,
    "right_option": 0x00000040,
    "left_control": 0x00000001,
    "right_control": 0x00002000,
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


def expand_tokens(names: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for name in names:
        if not name:
            continue
        tokens.add(name)
        tokens.add(canonicalize_part(name))
    return tokens


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
            elif part.startswith("f") and part[1:].isdigit():
                bits.append(part.upper())
            elif len(part) == 1:
                bits.append(part.upper())
            else:
                bits.append(part.replace("_", " ").title())
        return " + ".join(bits)

    def matches_tokens(self, tokens: set[str]) -> bool:
        if not self.parts:
            return False
        expanded = expand_tokens(tokens)
        return all(_part_present(part, expanded) for part in self.parts)


_MODE_RANK = {"refine": 3, "translate": 2, "transcript": 1}


def select_mode(tokens: set[str], chords: dict[str, HotkeyChord]) -> str | None:
    """Longest matching chord wins; on a tie, prefer more processing."""
    matches = [
        (name, chord) for name, chord in chords.items() if chord.matches_tokens(tokens)
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda item: (len(item[1].parts), _MODE_RANK.get(item[0], 0)),
        reverse=True,
    )
    return matches[0][0]


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
        if part not in _NAMED and len(part) != 1:
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


def _part_present(part: str, tokens: set[str]) -> bool:
    if part in tokens:
        return True
    family = canonicalize_part(part)
    if part == family:
        return f"left_{family}" in tokens or f"right_{family}" in tokens
    return False


class HoldMachine:
    """Pure hold-to-talk state. Feed currently pressed key tokens."""

    def __init__(
        self,
        on_press: Callable[[str], None],
        on_release: Callable[[], None],
    ):
        self._on_press = on_press
        self._on_release = on_release
        self.chords: dict[str, HotkeyChord] = {}
        self.held: str | None = None

    @property
    def has_chords(self) -> bool:
        return bool(self.chords)

    def set_chords(self, chords: dict[str, str] | str) -> None:
        if isinstance(chords, str):
            chords = {"transcript": chords}
        parsed: dict[str, HotkeyChord] = {}
        for name, spec in chords.items():
            if not spec or not str(spec).strip():
                continue
            parsed[name] = parse_hotkey(spec)
        self.chords = parsed
        if self.held and self.held not in self.chords:
            self.held = None
            self._on_release()

    def sync(self, tokens: set[str]) -> None:
        if self.held:
            chord = self.chords.get(self.held)
            if chord is None or not chord.matches_tokens(tokens):
                self.held = None
                self._on_release()
            return
        mode = select_mode(tokens, self.chords)
        if mode:
            self.held = mode
            self._on_press(mode)

    def reset(self, *, release: bool = True) -> None:
        if self.held is None:
            return
        self.held = None
        if not release:
            return
        try:
            self._on_release()
        except Exception:
            pass


class HoldListener:
    """Restartable hold-to-talk listener for one or more named chords."""

    def __init__(
        self,
        on_press: Callable[[str], None],
        on_release: Callable[[], None],
    ):
        self._machine = HoldMachine(on_press, on_release)
        self._tap: _MacEventTap | None = None

    def set_chords(self, chords: dict[str, str] | str) -> None:
        self._machine.set_chords(chords)

    def start(self, chords: dict[str, str] | str | None = None) -> None:
        if chords is not None:
            self.set_chords(chords)
        if self._tap is not None:
            return
        if not self._machine.has_chords:
            return
        if sys.platform != "darwin":
            logger.warning("hold-to-talk requires macOS")
            return
        self._tap = _MacEventTap(self._machine)
        self._tap.start()

    def restart(self, chords: dict[str, str] | str) -> None:
        self.stop()
        self.start(chords)

    def stop(self) -> None:
        tap = self._tap
        self._tap = None
        if tap is not None:
            tap.stop()
        self._machine.reset(release=True)


def start_hold_listener(
    chords: dict[str, str] | str,
    *,
    on_press: Callable[[str], None],
    on_release: Callable[[], None],
) -> HoldListener:
    listener = HoldListener(on_press, on_release)
    listener.start(chords)
    return listener


class _MacEventTap:
    def __init__(self, machine: HoldMachine):
        self._machine = machine
        self._mods: set[str] = set()
        self._keys: set[str] = set()
        self._local = None
        self._global = None

    def start(self) -> None:
        from AppKit import (
            NSEvent,
            NSEventMaskFlagsChanged,
            NSEventMaskKeyDown,
            NSEventMaskKeyUp,
        )

        mask = NSEventMaskKeyDown | NSEventMaskKeyUp | NSEventMaskFlagsChanged

        def local_handler(event):
            self._handle(event)
            return event

        def global_handler(event):
            self._handle(event)

        self._local = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            mask, local_handler
        )
        self._global = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mask, global_handler
        )

    def stop(self) -> None:
        from AppKit import NSEvent

        if self._local is not None:
            NSEvent.removeMonitor_(self._local)
            self._local = None
        if self._global is not None:
            NSEvent.removeMonitor_(self._global)
            self._global = None
        self._mods.clear()
        self._keys.clear()

    def _handle(self, event) -> None:
        try:
            self._dispatch(event)
        except Exception:
            logger.exception("hotkey event failed")

    def _dispatch(self, event) -> None:
        from AppKit import (
            NSEventTypeFlagsChanged,
            NSEventTypeKeyDown,
            NSEventTypeKeyUp,
        )

        etype = int(event.type())
        code = int(event.keyCode())
        if etype == int(NSEventTypeFlagsChanged):
            self._mods = _modifiers_from_flags(int(event.modifierFlags()), code)
        elif etype == int(NSEventTypeKeyDown):
            if bool(event.isARepeat()):
                return
            token = _non_modifier_token(event, code)
            if token is None:
                return
            self._keys.add(token)
        elif etype == int(NSEventTypeKeyUp):
            token = _non_modifier_token(event, code)
            if token is None:
                return
            self._keys.discard(token)
        else:
            return
        self._machine.sync(self._mods | self._keys)


def _non_modifier_token(event, code: int) -> str | None:
    name = hotkey_from_keycode(code)
    if name is not None:
        if canonicalize_part(name) in _FAMILIES:
            return None
        return name
    chars = event.charactersIgnoringModifiers()
    if not chars:
        return None
    text = str(chars).lower()
    if len(text) != 1 or not text.isprintable():
        return None
    return text


def _modifiers_from_flags(flags: int, key_code: int) -> set[str]:
    from AppKit import (
        NSEventModifierFlagCommand,
        NSEventModifierFlagControl,
        NSEventModifierFlagOption,
        NSEventModifierFlagShift,
    )

    family_flags = {
        "command": int(NSEventModifierFlagCommand),
        "option": int(NSEventModifierFlagOption),
        "control": int(NSEventModifierFlagControl),
        "shift": int(NSEventModifierFlagShift),
    }
    mods: set[str] = set()
    for name, bit in _DEVICE_BITS.items():
        if flags & bit:
            mods.add(name)
    for family, mask in family_flags.items():
        if not (flags & mask):
            continue
        left, right = f"left_{family}", f"right_{family}"
        if left in mods or right in mods:
            continue
        specific = hotkey_from_keycode(key_code)
        if specific is not None and canonicalize_part(specific) == family:
            mods.add(specific)
        else:
            mods.add(family)
    return mods
