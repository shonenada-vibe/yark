"""Hold-to-talk global hotkey."""

from __future__ import annotations

from collections.abc import Callable

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

HOTKEY_CHOICES: tuple[tuple[str, str], ...] = (
    ("right_option", "Right Option (⌥)"),
    ("left_option", "Left Option (⌥)"),
    ("right_command", "Right Command (⌘)"),
    ("left_command", "Left Command (⌘)"),
    ("right_control", "Right Control (⌃)"),
    ("left_control", "Left Control (⌃)"),
    ("f8", "F8"),
    ("f9", "F9"),
    ("f13", "F13"),
    ("f14", "F14"),
    ("f15", "F15"),
    ("f16", "F16"),
    ("f17", "F17"),
    ("f18", "F18"),
    ("f19", "F19"),
)

_LABELS: dict[str, str] = dict(HOTKEY_CHOICES)
_LABELS.update(
    {
        "option": "Option (⌥)",
        "alt": "Option (⌥)",
        "command": "Command (⌘)",
        "cmd": "Command (⌘)",
        "control": "Control (⌃)",
        "ctrl": "Control (⌃)",
        "shift": "Shift (⇧)",
        "right_shift": "Right Shift (⇧)",
        "left_shift": "Left Shift (⇧)",
        "space": "Space",
    }
)

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


def normalize_hotkey_name(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def hotkey_label(name: str) -> str:
    key = normalize_hotkey_name(name)
    return _LABELS.get(key, name)


def hotkey_from_keycode(code: int) -> str | None:
    return _KEYCODE_TO_NAME.get(int(code))


def resolve_hotkey(name: str):
    key = normalize_hotkey_name(name)
    if key == "fn":
        raise ConfigError(
            "fn is not a reliable hotkey; use right_option, right_command, f8, or f13"
        )
    if key in _NAMED_KEYS:
        return _NAMED_KEYS[key]
    if len(key) == 1:
        return keyboard.KeyCode.from_char(key)
    raise ConfigError(
        f"unknown hotkey {name!r}. Try right_option, right_command, f8, or f13"
    )


class HoldListener:
    """Restartable hold-to-talk listener."""

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
        target = resolve_hotkey(hotkey_name)

        def _press(key) -> None:
            if self._held or key != target:
                return
            self._held = True
            self._on_press()

        def _release(key) -> None:
            if not self._held or key != target:
                return
            self._held = False
            self._on_release()

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
