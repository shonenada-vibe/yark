"""macOS menu bar extra and settings panel."""

from __future__ import annotations

import logging
import os
import signal

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSEvent,
    NSEventMaskFlagsChanged,
    NSEventMaskKeyDown,
    NSEventMaskKeyUp,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSEventModifierFlagShift,
    NSEventTypeFlagsChanged,
    NSEventTypeKeyDown,
    NSEventTypeKeyUp,
    NSFloatingWindowLevel,
    NSFont,
    NSImage,
    NSLineBreakByWordWrapping,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSSquareStatusItemLength,
    NSStatusBar,
    NSTextAlignmentCenter,
    NSTextField,
    NSVariableStatusItemLength,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject

from yark.app import DictationRuntime
from yark.errors import ConfigError
from yark.hotkey import (
    ESCAPE_KEYCODE,
    format_chord,
    hotkey_label,
    recording_token_from_keycode,
)

logger = logging.getLogger("yark.statusbar")

_FAMILY_FLAGS = {
    "command": NSEventModifierFlagCommand,
    "option": NSEventModifierFlagOption,
    "control": NSEventModifierFlagControl,
    "shift": NSEventModifierFlagShift,
}

_RECORD_MASK = NSEventMaskKeyDown | NSEventMaskKeyUp | NSEventMaskFlagsChanged


class YarkAppDelegate(NSObject):
    runtime = objc.ivar()
    status_item = objc.ivar()
    status_line = objc.ivar()
    shortcut_line = objc.ivar()
    settings_window = objc.ivar()
    shortcut_display = objc.ivar()
    record_button = objc.ivar()
    hint = objc.ivar()
    local_monitor = objc.ivar()
    global_monitor = objc.ivar()
    recording = objc.ivar()
    _listening = objc.ivar()
    _started = objc.ivar()

    def initWithRuntime_(self, runtime: DictationRuntime):
        self = objc.super(YarkAppDelegate, self).init()
        if self is None:
            return None
        self.runtime = runtime
        self.status_item = None
        self.status_line = None
        self.shortcut_line = None
        self.settings_window = None
        self.shortcut_display = None
        self.record_button = None
        self.hint = None
        self.local_monitor = None
        self.global_monitor = None
        self.recording = False
        self._listening = False
        self._started = False
        self._record_down: set[str] = set()
        self._record_peak: set[str] = set()
        runtime.on_listening = self.setListening_
        return self

    def applicationDidFinishLaunching_(self, notification) -> None:
        if self.status_item is None:
            self.finishLaunch()

    def applicationWillTerminate_(self, notification) -> None:
        self._stop_recording(resume=False)
        self.runtime.shutdown()

    def settings_(self, sender) -> None:
        self._stop_recording()
        window = self._settings_window()
        NSApp.activateIgnoringOtherApps_(True)
        window.makeKeyAndOrderFront_(None)
        self._sync_shortcut_display()

    def quit_(self, sender) -> None:
        NSApp.terminate_(None)

    def recordShortcut_(self, sender) -> None:
        if self.recording:
            self._stop_recording()
            return
        self.runtime.pause_hotkey()
        self.recording = True
        self._record_down = set()
        self._record_peak = set()
        self.record_button.setTitle_("Hold keys, then release… (Esc cancels)")
        self._update_record_preview()

        def local_handler(event):
            return self._on_record_event(event)

        def global_handler(event):
            self._on_record_event(event)

        self.local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            _RECORD_MASK, local_handler
        )
        self.global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            _RECORD_MASK, global_handler
        )

    def finishLaunch(self) -> None:
        if self._started:
            return
        self._started = True
        self._build_status_item()
        self.runtime.start()
        self.setListening_(False)

    def setListening_(self, listening) -> None:
        self._listening = bool(listening)

        def apply() -> None:
            if self.status_item is None:
                return
            image = _mic_image(self._listening)
            button = self.status_item.button()
            if image is not None:
                self.status_item.setLength_(NSSquareStatusItemLength)
                button.setImage_(image)
                button.setTitle_("")
            else:
                self.status_item.setLength_(NSVariableStatusItemLength)
                button.setImage_(None)
                button.setTitle_("●" if self._listening else "Yark")
            status = "Listening…" if self._listening else "Ready"
            self.status_line.setTitle_(status)
            label = hotkey_label(self.runtime.hotkey)
            self.shortcut_line.setTitle_(f"Hold {label} to dictate")
            button.setToolTip_(f"yark — {status.lower()}. Hold {label} to dictate.")
            self._sync_shortcut_display()

        _on_main(apply)

    def _build_status_item(self) -> None:
        item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSSquareStatusItemLength
        )
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)

        status = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Ready", None, ""
        )
        status.setEnabled_(False)
        menu.addItem_(status)

        shortcut = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Hold {hotkey_label(self.runtime.hotkey)} to dictate", None, ""
        )
        shortcut.setEnabled_(False)
        menu.addItem_(shortcut)
        menu.addItem_(NSMenuItem.separatorItem())

        settings = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings…", "settings:", ","
        )
        settings.setTarget_(self)
        menu.addItem_(settings)
        menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit yark", "quit:", "q"
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)

        item.setMenu_(menu)
        self.status_item = item
        self.status_line = status
        self.shortcut_line = shortcut

    def _settings_window(self) -> NSWindow:
        if self.settings_window is not None:
            return self.settings_window

        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 380, 200),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        window.setTitle_("Yark Settings")
        window.setReleasedWhenClosed_(False)
        window.setLevel_(NSFloatingWindowLevel)
        window.center()

        content = window.contentView()
        assert content is not None

        title = _label("Hold-to-talk shortcut", NSMakeRect(20, 154, 340, 22), bold=True)
        content.addSubview_(title)

        display = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 112, 340, 32))
        display.setEditable_(False)
        display.setBezeled_(True)
        display.setAlignment_(NSTextAlignmentCenter)
        display.setFont_(NSFont.systemFontOfSize_(16.0))
        content.addSubview_(display)

        record = NSButton.alloc().initWithFrame_(NSMakeRect(20, 70, 340, 32))
        record.setTitle_("Record shortcut")
        record.setBezelStyle_(NSBezelStyleRounded)
        record.setTarget_(self)
        record.setAction_("recordShortcut:")
        content.addSubview_(record)

        hint = _label(_shortcut_hint(), NSMakeRect(20, 16, 340, 48))
        hint.setTextColor_(NSColor.secondaryLabelColor())
        hint.setMaximumNumberOfLines_(3)
        hint.setLineBreakMode_(NSLineBreakByWordWrapping)
        content.addSubview_(hint)

        self.settings_window = window
        self.shortcut_display = display
        self.record_button = record
        self.hint = hint
        self._sync_shortcut_display()
        return window

    def _sync_shortcut_display(self) -> None:
        if self.shortcut_display is None:
            return
        if self.recording:
            return
        self.shortcut_display.setStringValue_(hotkey_label(self.runtime.hotkey))

    def _update_record_preview(self) -> None:
        if self.shortcut_display is None:
            return
        current = self._record_down or self._record_peak
        if current:
            self.shortcut_display.setStringValue_(hotkey_label(format_chord(current)))
        else:
            self.shortcut_display.setStringValue_("Waiting for keys…")

    def _apply_hotkey(self, name: str) -> bool:
        try:
            self.runtime.set_hotkey(name)
        except ConfigError as exc:
            logger.warning("cannot set shortcut: %s", exc)
            return False
        self.setListening_(self._listening)
        return True

    def _on_record_event(self, event):
        if not self.recording:
            return event
        code = int(event.keyCode())
        if code == ESCAPE_KEYCODE:
            self._stop_recording()
            return None
        token = recording_token_from_keycode(code)
        if token is None:
            return event

        etype = int(event.type())
        if etype == int(NSEventTypeFlagsChanged):
            mask = _FAMILY_FLAGS.get(token)
            is_down = True if mask is None else bool(int(event.modifierFlags()) & int(mask))
        elif etype == int(NSEventTypeKeyDown):
            is_down = True
        elif etype == int(NSEventTypeKeyUp):
            is_down = False
        else:
            return event

        if is_down:
            self._record_down.add(token)
            if len(self._record_down) >= len(self._record_peak):
                self._record_peak = set(self._record_down)
            self._update_record_preview()
        else:
            self._record_down.discard(token)
            self._update_record_preview()
            if not self._record_down and self._record_peak:
                spec = format_chord(self._record_peak)
                ok = self._apply_hotkey(spec)
                self._stop_recording(resume=not ok)
                return None
        return None

    def _stop_recording(self, resume: bool = True) -> None:
        was_recording = bool(self.recording)
        self.recording = False
        self._record_down = set()
        self._record_peak = set()
        if self.local_monitor is not None:
            NSEvent.removeMonitor_(self.local_monitor)
            self.local_monitor = None
        if self.global_monitor is not None:
            NSEvent.removeMonitor_(self.global_monitor)
            self.global_monitor = None
        if self.record_button is not None:
            self.record_button.setTitle_("Record shortcut")
        self._sync_shortcut_display()
        if was_recording and resume:
            self.runtime.resume_hotkey()


def run_status_app(runtime: DictationRuntime) -> None:
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = YarkAppDelegate.alloc().initWithRuntime_(runtime)
    app.setDelegate_(delegate)
    delegate.finishLaunch()

    def _sigint(*_args) -> None:
        NSApp.terminate_(None)

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)
    app.run()


def _mic_image(listening: bool):
    name = "mic.fill" if listening else "mic"
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, "yark")
    if image is None:
        return None
    image.setTemplate_(True)
    image.setSize_((18.0, 18.0))
    return image


def _label(text: str, frame, *, bold: bool = False) -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setStringValue_(text)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    size = 13.0 if bold else 11.0
    font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    field.setFont_(font)
    return field


def _shortcut_hint() -> str:
    hint = (
        "Hold the shortcut to dictate, release to stop. "
        "Record a chord such as ⌘ + ⌥. Saved to config.toml."
    )
    if os.environ.get("YARK_HOTKEY"):
        hint += " YARK_HOTKEY is set and will override this on the next launch."
    return hint


def _on_main(callback) -> None:
    from Foundation import NSOperationQueue, NSThread

    if NSThread.isMainThread():
        callback()
    else:
        NSOperationQueue.mainQueue().addOperationWithBlock_(callback)
