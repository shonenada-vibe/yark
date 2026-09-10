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
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSEventModifierFlagShift,
    NSEventTypeFlagsChanged,
    NSFloatingWindowLevel,
    NSFont,
    NSImage,
    NSLineBreakByWordWrapping,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPopUpButton,
    NSSquareStatusItemLength,
    NSStatusBar,
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
    HOTKEY_CHOICES,
    hotkey_from_keycode,
    hotkey_label,
)

logger = logging.getLogger("yark.statusbar")

_MODIFIER_FLAGS = {
    "right_option": NSEventModifierFlagOption,
    "left_option": NSEventModifierFlagOption,
    "right_command": NSEventModifierFlagCommand,
    "left_command": NSEventModifierFlagCommand,
    "right_control": NSEventModifierFlagControl,
    "left_control": NSEventModifierFlagControl,
    "right_shift": NSEventModifierFlagShift,
    "left_shift": NSEventModifierFlagShift,
}


class YarkAppDelegate(NSObject):
    runtime = objc.ivar()
    status_item = objc.ivar()
    status_line = objc.ivar()
    shortcut_line = objc.ivar()
    settings_window = objc.ivar()
    popup = objc.ivar()
    record_button = objc.ivar()
    hint = objc.ivar()
    monitor = objc.ivar()
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
        self.popup = None
        self.record_button = None
        self.hint = None
        self.monitor = None
        self.recording = False
        self._listening = False
        self._started = False
        runtime.on_listening = self.setListening_
        return self

    def applicationDidFinishLaunching_(self, notification) -> None:
        if self.status_item is None:
            self.finishLaunch()

    def applicationWillTerminate_(self, notification) -> None:
        self._stop_recording()
        self.runtime.shutdown()

    def settings_(self, sender) -> None:
        self._stop_recording()
        window = self._settings_window()
        NSApp.activateIgnoringOtherApps_(True)
        window.makeKeyAndOrderFront_(None)
        self._sync_popup()

    def quit_(self, sender) -> None:
        NSApp.terminate_(None)

    def shortcutPicked_(self, sender) -> None:
        item = sender.selectedItem()
        if item is None:
            return
        name = item.representedObject()
        if name:
            self._apply_hotkey(str(name))

    def recordShortcut_(self, sender) -> None:
        if self.recording:
            self._stop_recording()
            return
        self.recording = True
        self.record_button.setTitle_("Press a key… (Esc cancels)")
        mask = NSEventMaskKeyDown | NSEventMaskFlagsChanged

        def handler(event):
            return self._on_record_event(event)

        self.monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            mask, handler
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
            self._sync_popup()

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
            NSMakeRect(0, 0, 380, 196),
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

        title = _label("Hold-to-talk shortcut", NSMakeRect(20, 150, 340, 22), bold=True)
        content.addSubview_(title)

        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(20, 114, 340, 28), False
        )
        for name, label in HOTKEY_CHOICES:
            popup.addItemWithTitle_(label)
            popup.lastItem().setRepresentedObject_(name)
        popup.setTarget_(self)
        popup.setAction_("shortcutPicked:")
        content.addSubview_(popup)

        record = NSButton.alloc().initWithFrame_(NSMakeRect(20, 72, 340, 32))
        record.setTitle_("Click to record a new shortcut")
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
        self.popup = popup
        self.record_button = record
        self.hint = hint
        self._sync_popup()
        return window

    def _sync_popup(self) -> None:
        if self.popup is None:
            return
        current = self.runtime.hotkey
        names = [name for name, _label in HOTKEY_CHOICES]
        if current not in names:
            self.popup.addItemWithTitle_(hotkey_label(current))
            self.popup.lastItem().setRepresentedObject_(current)
        index = 0
        for i in range(self.popup.numberOfItems()):
            item = self.popup.itemAtIndex_(i)
            if item is not None and str(item.representedObject() or "") == current:
                index = i
                break
        self.popup.selectItemAtIndex_(index)

    def _apply_hotkey(self, name: str) -> None:
        try:
            self.runtime.set_hotkey(name)
        except ConfigError as exc:
            logger.warning("cannot set shortcut: %s", exc)
            return
        self.setListening_(self._listening)

    def _on_record_event(self, event):
        if not self.recording:
            return event
        code = int(event.keyCode())
        if code == ESCAPE_KEYCODE:
            self._stop_recording()
            return None
        name = hotkey_from_keycode(code)
        if name is None:
            return event
        if int(event.type()) == int(NSEventTypeFlagsChanged):
            mask = _MODIFIER_FLAGS.get(name)
            if mask is not None and not (int(event.modifierFlags()) & int(mask)):
                return None
        self._apply_hotkey(name)
        self._stop_recording()
        return None

    def _stop_recording(self) -> None:
        self.recording = False
        if self.monitor is not None:
            NSEvent.removeMonitor_(self.monitor)
            self.monitor = None
        if self.record_button is not None:
            self.record_button.setTitle_("Click to record a new shortcut")


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
    hint = "Hold the key to dictate, release to stop. The shortcut is saved to config.toml."
    if os.environ.get("YARK_HOTKEY"):
        hint += " YARK_HOTKEY is set and will override this on the next launch."
    return hint


def _on_main(callback) -> None:
    from Foundation import NSOperationQueue, NSThread

    if NSThread.isMainThread():
        callback()
    else:
        NSOperationQueue.mainQueue().addOperationWithBlock_(callback)
