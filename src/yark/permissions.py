from __future__ import annotations

import sys


def check_microphone(prompt: bool = False) -> bool:
    if sys.platform != "darwin":
        return True
    try:
        from AVFoundation import (
            AVCaptureDevice,
            AVMediaTypeAudio,
            AVAuthorizationStatusAuthorized,
            AVAuthorizationStatusNotDetermined,
        )
    except Exception:
        return True
    status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
    if status == AVAuthorizationStatusAuthorized:
        return True
    if prompt and status == AVAuthorizationStatusNotDetermined:
        # Opening the mic stream later will trigger the system prompt.
        return False
    return False


def check_accessibility(prompt: bool = True) -> bool:
    if sys.platform != "darwin":
        return True
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
    except Exception:
        return True
    options = None
    if prompt:
        try:
            from ApplicationServices import kAXTrustedCheckOptionPrompt

            options = {kAXTrustedCheckOptionPrompt: True}
        except Exception:
            options = {"AXTrustedCheckOptionPrompt": True}
    try:
        return bool(AXIsProcessTrustedWithOptions(options))
    except Exception:
        return False
