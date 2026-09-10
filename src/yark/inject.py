"""Insert recognized text into the focused macOS application."""

from __future__ import annotations

import logging
import sys
import time

from yark.errors import YarkError

logger = logging.getLogger("yark.inject")

IS_MAC = sys.platform == "darwin"
_UNICODE_CHUNK = 16


def inject_text(text: str, mode: str) -> None:
    if not text:
        return
    if mode == "print":
        print(text, end="", flush=True)
        return
    if not IS_MAC:
        raise YarkError("text injection is only implemented on macOS")
    if mode == "paste":
        _paste(text)
        return
    if mode == "unicode":
        try:
            _type_unicode(text)
        except Exception:
            logger.exception("unicode inject failed; falling back to paste")
            _paste(text)
        return
    raise YarkError(f"unknown inject mode {mode!r}; use unicode, paste, or print")


def _type_unicode(text: str) -> None:
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventKeyboardSetUnicodeString,
        CGEventPost,
        CGEventSetFlags,
        kCGHIDEventTap,
    )

    for i in range(0, len(text), _UNICODE_CHUNK):
        chunk = text[i : i + _UNICODE_CHUNK]
        utf16_len = len(chunk.encode("utf-16-le")) // 2
        down = CGEventCreateKeyboardEvent(None, 0, True)
        CGEventKeyboardSetUnicodeString(down, utf16_len, chunk)
        CGEventSetFlags(down, 0)
        CGEventPost(kCGHIDEventTap, down)
        up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventSetFlags(up, 0)
        CGEventPost(kCGHIDEventTap, up)


def _paste(text: str) -> None:
    from AppKit import NSPasteboard, NSPasteboardTypeString
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventPost,
        CGEventSetFlags,
        kCGEventFlagMaskCommand,
        kCGHIDEventTap,
    )

    pasteboard = NSPasteboard.generalPasteboard()
    previous = pasteboard.stringForType_(NSPasteboardTypeString)
    pasteboard.clearContents()
    pasteboard.setString_forType_(text, NSPasteboardTypeString)

    # kVK_ANSI_V = 0x09
    down = CGEventCreateKeyboardEvent(None, 0x09, True)
    CGEventSetFlags(down, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, down)
    up = CGEventCreateKeyboardEvent(None, 0x09, False)
    CGEventSetFlags(up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, up)

    time.sleep(0.05)
    pasteboard.clearContents()
    if previous:
        pasteboard.setString_forType_(previous, NSPasteboardTypeString)


def beep() -> None:
    if not IS_MAC:
        print("\a", end="", flush=True)
        return
    try:
        from AppKit import NSSound

        NSSound.beep()
    except Exception:
        print("\a", end="", flush=True)
