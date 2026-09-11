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
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBezelBorder,
    NSBezelStyleRounded,
    NSButton,
    NSButtonTypeSwitch,
    NSColor,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSEvent,
    NSEventTypeApplicationDefined,
    NSEventMaskFlagsChanged,
    NSEventMaskKeyDown,
    NSEventMaskKeyUp,
    NSEventModifierFlagCommand,
    NSEventModifierFlagDeviceIndependentFlagsMask,
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
    NSScrollView,
    NSSecureTextField,
    NSSquareStatusItemLength,
    NSStatusBar,
    NSTimer,
    NSTabView,
    NSTabViewItem,
    NSTextAlignmentCenter,
    NSTextField,
    NSTextView,
    NSVariableStatusItemLength,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject

from yark.app import DictationRuntime
from yark.config import LlmConfig, LlmFeatureConfig
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
    record_buttons = objc.ivar()
    hint = objc.ivar()
    local_monitor = objc.ivar()
    global_monitor = objc.ivar()
    edit_monitor = objc.ivar()
    recording = objc.ivar()
    base_url_field = objc.ivar()
    model_field = objc.ivar()
    shared_key_field = objc.ivar()
    refine_enable = objc.ivar()
    refine_key_field = objc.ivar()
    refine_prompt_view = objc.ivar()
    translate_enable = objc.ivar()
    translate_key_field = objc.ivar()
    translate_prompt_view = objc.ivar()
    heartbeat = objc.ivar()
    _listening = objc.ivar()
    _started = objc.ivar()
    _stop_requested = objc.ivar()

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
        self.record_buttons = None
        self._record_slot = "transcript"
        self.shortcut_displays: dict = {}
        self.hint = None
        self.base_url_field = None
        self.model_field = None
        self.shared_key_field = None
        self.refine_enable = None
        self.refine_key_field = None
        self.refine_prompt_view = None
        self.translate_enable = None
        self.translate_key_field = None
        self.translate_prompt_view = None
        self.local_monitor = None
        self.global_monitor = None
        self.edit_monitor = None
        self.recording = False
        self._listening = False
        self._started = False
        self._stop_requested = False
        self.heartbeat = None
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
        self._load_llm_fields()
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        NSApp.activateIgnoringOtherApps_(True)
        window.makeKeyAndOrderFront_(None)
        self._start_edit_monitor()
        self._sync_shortcut_display()

    def quit_(self, sender) -> None:
        self._request_stop()

    def tick_(self, timer) -> None:
        if self._stop_requested:
            self._request_stop()

    def _request_stop(self) -> None:
        self._stop_requested = False
        if self.heartbeat is not None:
            self.heartbeat.invalidate()
            self.heartbeat = None
        try:
            self._save_llm_fields()
        except Exception:
            logger.debug("save on quit failed", exc_info=True)
        self._stop_recording(resume=False)
        NSApp.stop_(None)
        _poke_run_loop()

    def windowWillClose_(self, notification) -> None:
        self._stop_edit_monitor()
        self._save_llm_fields()
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    def windowDidResignKey_(self, notification) -> None:
        self._save_llm_fields()

    def llmToggle_(self, sender) -> None:
        self._save_llm_fields()

    def controlTextDidEndEditing_(self, notification) -> None:
        self._save_llm_fields()

    def recordShortcut_(self, sender) -> None:
        if self.recording:
            self._stop_recording()
            return
        slots = ("transcript", "translate", "refine")
        tag = int(sender.tag()) if sender is not None else 0
        self._record_slot = slots[tag] if 0 <= tag < len(slots) else "transcript"
        self.runtime.pause_hotkey()
        self.recording = True
        self._record_down = set()
        self._record_peak = set()
        self.record_button = sender
        if sender is not None:
            sender.setTitle_("Hold keys…")
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
            mode = self.runtime.session_mode if self._listening else ""
            status = f"Listening… {_mode_title(mode)}" if self._listening else "Ready"
            self.status_line.setTitle_(status)
            summary = _shortcut_summary(self.runtime.cfg.input.hotkey_map())
            self.shortcut_line.setTitle_(summary)
            button.setToolTip_(f"yark — {status}. {summary}")
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
            _shortcut_summary(self.runtime.cfg.input.hotkey_map()), None, ""
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
            NSMakeRect(0, 0, 540, 556),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        window.setTitle_("Yark Settings")
        window.setReleasedWhenClosed_(False)
        window.setLevel_(NSFloatingWindowLevel)
        window.setDelegate_(self)
        window.center()

        content = window.contentView()
        assert content is not None

        content.addSubview_(_label("OpenAI-compatible API", NSMakeRect(20, 514, 500, 20), bold=True))
        content.addSubview_(_label("Base URL", NSMakeRect(20, 490, 80, 18)))
        base_url = _editable_field(NSMakeRect(104, 486, 416, 24))
        base_url.setDelegate_(self)
        content.addSubview_(base_url)

        content.addSubview_(_label("Model", NSMakeRect(20, 458, 80, 18)))
        model = _editable_field(NSMakeRect(104, 454, 416, 24))
        model.setDelegate_(self)
        content.addSubview_(model)

        content.addSubview_(_label("API key", NSMakeRect(20, 426, 80, 18)))
        shared_key = NSSecureTextField.alloc().initWithFrame_(NSMakeRect(104, 422, 416, 24))
        shared_key.setDelegate_(self)
        shared_key.setMenu_(_field_edit_menu(secure=True))
        content.addSubview_(shared_key)

        tabs = NSTabView.alloc().initWithFrame_(NSMakeRect(16, 16, 508, 390))
        shortcut_item = NSTabViewItem.alloc().initWithIdentifier_("shortcut")
        shortcut_item.setLabel_("Shortcut")
        shortcut_item.setView_(self._build_shortcut_tab())
        tabs.addTabViewItem_(shortcut_item)

        refine_item = NSTabViewItem.alloc().initWithIdentifier_("refine")
        refine_item.setLabel_("Refine")
        refine_view, self.refine_enable, self.refine_key_field, self.refine_prompt_view = (
            self._build_feature_tab("Enable refine", "refineToggle:")
        )
        refine_item.setView_(refine_view)
        tabs.addTabViewItem_(refine_item)

        translate_item = NSTabViewItem.alloc().initWithIdentifier_("translate")
        translate_item.setLabel_("Translate")
        translate_view, self.translate_enable, self.translate_key_field, self.translate_prompt_view = (
            self._build_feature_tab("Enable translate", "translateToggle:")
        )
        translate_item.setView_(translate_view)
        tabs.addTabViewItem_(translate_item)

        content.addSubview_(tabs)

        self.settings_window = window
        self.base_url_field = base_url
        self.model_field = model
        self.shared_key_field = shared_key
        self._load_llm_fields()
        return window

    def _build_shortcut_tab(self) -> NSView:
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 480, 340))
        title = _label("Hold-to-talk shortcuts", NSMakeRect(16, 308, 448, 22), bold=True)
        view.addSubview_(title)

        rows = (
            ("transcript", "1. Transcript"),
            ("translate", "2. Translate"),
            ("refine", "3. Translate + Refine"),
        )
        displays: dict[str, object] = {}
        buttons: dict[str, object] = {}
        top = 270
        for index, (slot, caption) in enumerate(rows):
            y = top - index * 70
            view.addSubview_(_label(caption, NSMakeRect(16, y + 28, 448, 18), bold=True))
            display = NSTextField.alloc().initWithFrame_(NSMakeRect(16, y, 320, 26))
            display.setEditable_(False)
            display.setBezeled_(True)
            display.setAlignment_(NSTextAlignmentCenter)
            view.addSubview_(display)
            record = NSButton.alloc().initWithFrame_(NSMakeRect(344, y - 2, 120, 30))
            record.setTitle_("Record")
            record.setBezelStyle_(NSBezelStyleRounded)
            record.setTarget_(self)
            record.setAction_("recordShortcut:")
            record.setTag_(index)
            view.addSubview_(record)
            displays[slot] = display
            buttons[slot] = record

        hint = _label(_shortcut_hint(), NSMakeRect(16, 8, 448, 56))
        hint.setTextColor_(NSColor.secondaryLabelColor())
        hint.setMaximumNumberOfLines_(4)
        hint.setLineBreakMode_(NSLineBreakByWordWrapping)
        view.addSubview_(hint)

        self.shortcut_displays = displays
        self.record_buttons = buttons
        self.shortcut_display = displays.get("transcript")
        self.record_button = buttons.get("transcript")
        self.hint = hint
        self._sync_shortcut_display()
        return view

    def _build_feature_tab(self, enable_title: str, action: str):
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 480, 340))
        enable = NSButton.alloc().initWithFrame_(NSMakeRect(16, 300, 448, 24))
        enable.setButtonType_(NSButtonTypeSwitch)
        enable.setTitle_(enable_title)
        enable.setTarget_(self)
        enable.setAction_(action)
        view.addSubview_(enable)

        view.addSubview_(_label("API key", NSMakeRect(16, 270, 80, 18)))
        key_field = NSSecureTextField.alloc().initWithFrame_(NSMakeRect(96, 266, 368, 24))
        key_field.setDelegate_(self)
        key_field.setMenu_(_field_edit_menu(secure=True))
        view.addSubview_(key_field)

        view.addSubview_(_label("Prompt", NSMakeRect(16, 236, 80, 18)))
        scroll, prompt = _prompt_editor(NSMakeRect(16, 16, 448, 216))
        view.addSubview_(scroll)
        return view, enable, key_field, prompt

    def refineToggle_(self, sender) -> None:
        self._save_llm_fields()

    def translateToggle_(self, sender) -> None:
        self._save_llm_fields()

    def _load_llm_fields(self) -> None:
        llm = self.runtime.cfg.llm
        if self.base_url_field is None:
            return
        self.base_url_field.setStringValue_(llm.base_url)
        self.model_field.setStringValue_(llm.model)
        self.shared_key_field.setStringValue_(llm.api_key)
        self.refine_enable.setState_(
            NSControlStateValueOn if llm.refine.enabled else NSControlStateValueOff
        )
        self.refine_key_field.setStringValue_(llm.refine.api_key)
        self.refine_prompt_view.setString_(llm.refine.prompt)
        self.translate_enable.setState_(
            NSControlStateValueOn if llm.translate.enabled else NSControlStateValueOff
        )
        self.translate_key_field.setStringValue_(llm.translate.api_key)
        self.translate_prompt_view.setString_(llm.translate.prompt)

    def _save_llm_fields(self) -> None:
        if self.base_url_field is None:
            return
        current = self.runtime.cfg.llm
        llm = LlmConfig(
            base_url=str(self.base_url_field.stringValue() or "").strip() or current.base_url,
            model=str(self.model_field.stringValue() or "").strip() or current.model,
            api_key=str(self.shared_key_field.stringValue() or ""),
            timeout=current.timeout,
            refine=LlmFeatureConfig(
                enabled=int(self.refine_enable.state()) == int(NSControlStateValueOn),
                api_key=str(self.refine_key_field.stringValue() or ""),
                prompt=str(self.refine_prompt_view.string() or ""),
            ),
            translate=LlmFeatureConfig(
                enabled=int(self.translate_enable.state()) == int(NSControlStateValueOn),
                api_key=str(self.translate_key_field.stringValue() or ""),
                prompt=str(self.translate_prompt_view.string() or ""),
            ),
        )
        if llm == current:
            return
        try:
            self.runtime.update_llm(llm)
        except Exception:
            logger.exception("failed to save LLM settings")

    def _sync_shortcut_display(self) -> None:
        displays = getattr(self, "shortcut_displays", None) or {}
        if self.recording:
            return
        mapping = self.runtime.cfg.input.hotkey_map()
        for slot, display in displays.items():
            spec = mapping.get(slot, "")
            display.setStringValue_(hotkey_label(spec) if spec else "Not set")
        if self.shortcut_display is not None and not displays:
            self.shortcut_display.setStringValue_(hotkey_label(self.runtime.hotkey))

    def _update_record_preview(self) -> None:
        displays = getattr(self, "shortcut_displays", None) or {}
        display = displays.get(getattr(self, "_record_slot", "transcript"))
        if display is None:
            display = self.shortcut_display
        if display is None:
            return
        current = self._record_down or self._record_peak
        if current:
            display.setStringValue_(hotkey_label(format_chord(current)))
        else:
            display.setStringValue_("Waiting for keys…")

    def _apply_hotkey(self, name: str) -> bool:
        slot = getattr(self, "_record_slot", "transcript") or "transcript"
        try:
            self.runtime.set_hotkey(name, slot)
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
        buttons = getattr(self, "record_buttons", None) or {}
        for button in buttons.values():
            button.setTitle_("Record")
        if self.record_button is not None and not buttons:
            self.record_button.setTitle_("Record")
        self._sync_shortcut_display()
        if was_recording and resume:
            self.runtime.resume_hotkey()

    def _start_edit_monitor(self) -> None:
        if self.edit_monitor is not None:
            return

        def handler(event):
            return self._on_edit_key(event)

        self.edit_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, handler
        )

    def _stop_edit_monitor(self) -> None:
        if self.edit_monitor is None:
            return
        NSEvent.removeMonitor_(self.edit_monitor)
        self.edit_monitor = None

    def _on_edit_key(self, event):
        if self.recording:
            return event
        window = self.settings_window
        if window is None or not window.isKeyWindow():
            return event
        flags = int(event.modifierFlags()) & int(NSEventModifierFlagDeviceIndependentFlagsMask)
        chars = event.charactersIgnoringModifiers()
        if not chars:
            return event
        key = str(chars).lower()
        command = int(NSEventModifierFlagCommand)
        shift = int(NSEventModifierFlagShift)
        action = None
        if flags == command:
            action = {"v": "paste:", "c": "copy:", "x": "cut:", "a": "selectAll:", "z": "undo:"}.get(key)
        elif flags == (command | shift) and key == "z":
            action = "redo:"
        if not action:
            return event
        if NSApp.sendAction_to_from_(action, None, None):
            return None
        return event


def run_status_app(runtime: DictationRuntime) -> None:
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = YarkAppDelegate.alloc().initWithRuntime_(runtime)
    app.setDelegate_(delegate)
    _install_main_menu(delegate)
    delegate.finishLaunch()
    delegate.heartbeat = _start_heartbeat(delegate)

    def _sigint(*_args) -> None:
        delegate._stop_requested = True

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)
    print("yark is running. Ctrl+C to quit.", flush=True)
    try:
        app.run()
    except KeyboardInterrupt:
        delegate._request_stop()
    print("\nyark stopped.", flush=True)


def _start_heartbeat(delegate: YarkAppDelegate):
    """Wake Python on the main run loop so SIGINT/Ctrl+C can be handled."""
    from Foundation import NSRunLoop, NSRunLoopCommonModes

    timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
        0.2, delegate, "tick:", None, True
    )
    NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
    return timer


def _poke_run_loop() -> None:
    """NSApp.stop_ only returns from run() after another event is processed."""
    event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        NSEventTypeApplicationDefined,
        (0.0, 0.0),
        0,
        0.0,
        0,
        None,
        0,
        0,
        0,
    )
    if event is not None:
        NSApp.postEvent_atStart_(event, True)


def _install_main_menu(delegate) -> None:
    """Edit menu key equivalents (⌘V) only work if the app has a main menu."""
    menubar = NSMenu.alloc().init()
    app_item = NSMenuItem.alloc().init()
    menubar.addItem_(app_item)
    app_menu = NSMenu.alloc().init()
    app_item.setSubmenu_(app_menu)
    quit_item = app_menu.addItemWithTitle_action_keyEquivalent_("Quit yark", "quit:", "q")
    quit_item.setTarget_(delegate)

    edit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Edit", None, "")
    menubar.addItem_(edit_item)
    edit = NSMenu.alloc().initWithTitle_("Edit")
    edit.addItemWithTitle_action_keyEquivalent_("Undo", "undo:", "z")
    edit.addItemWithTitle_action_keyEquivalent_("Redo", "redo:", "Z")
    edit.addItem_(NSMenuItem.separatorItem())
    edit.addItemWithTitle_action_keyEquivalent_("Cut", "cut:", "x")
    edit.addItemWithTitle_action_keyEquivalent_("Copy", "copy:", "c")
    edit.addItemWithTitle_action_keyEquivalent_("Paste", "paste:", "v")
    edit.addItemWithTitle_action_keyEquivalent_("Select All", "selectAll:", "a")
    edit_item.setSubmenu_(edit)
    NSApp.setMainMenu_(menubar)


def _field_edit_menu(*, secure: bool = False) -> NSMenu:
    menu = NSMenu.alloc().init()
    if not secure:
        menu.addItemWithTitle_action_keyEquivalent_("Cut", "cut:", "")
        menu.addItemWithTitle_action_keyEquivalent_("Copy", "copy:", "")
    menu.addItemWithTitle_action_keyEquivalent_("Paste", "paste:", "")
    menu.addItemWithTitle_action_keyEquivalent_("Select All", "selectAll:", "")
    return menu


def _editable_field(frame) -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setBezeled_(True)
    field.setEditable_(True)
    field.setSelectable_(True)
    field.setMenu_(_field_edit_menu())
    return field


def _prompt_editor(frame):
    scroll = NSScrollView.alloc().initWithFrame_(frame)
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(NSBezelBorder)
    scroll.setAutohidesScrollers_(True)
    size = scroll.contentSize()
    view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, size.width, size.height))
    view.setMinSize_((size.width, size.height))
    view.setMaxSize_((size.width, 1_000_000.0))
    view.setVerticallyResizable_(True)
    view.setHorizontallyResizable_(False)
    view.setRichText_(False)
    view.setAllowsUndo_(True)
    view.setImportsGraphics_(False)
    font = NSFont.userFixedPitchFontOfSize_(12.0) or NSFont.systemFontOfSize_(12.0)
    view.setFont_(font)
    scroll.setDocumentView_(view)
    return scroll, view


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


def _mode_title(mode: str) -> str:
    return {
        "transcript": "Transcript",
        "translate": "Translate",
        "refine": "Translate + Refine",
    }.get(mode, mode or "Transcript")


def _shortcut_summary(mapping: dict[str, str]) -> str:
    parts = []
    for slot in ("transcript", "translate", "refine"):
        spec = mapping.get(slot)
        if spec:
            parts.append(f"{_mode_title(slot)} {hotkey_label(spec)}")
    return " · ".join(parts) if parts else "No shortcuts set"


def _shortcut_hint() -> str:
    hint = (
        "Three hold-to-talk levels: transcript, translate, or translate+refine. "
        "Longer chords win if they overlap. Saved to config.toml."
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
