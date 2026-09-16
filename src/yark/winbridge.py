"""Windows helpers used from WSL (preferred) or native Windows Python."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from yark.errors import YarkError
from yark.hotkey import HoldMachine, expand_tokens

logger = logging.getLogger("yark.winbridge")

_SENTINEL = object()


def running_in_wsl() -> bool:
    if sys.platform == "win32":
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        text = Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in text or "wsl" in text


def on_windows_host() -> bool:
    return sys.platform == "win32" or running_in_wsl()


def find_powershell() -> str | None:
    for name in ("powershell.exe", "pwsh.exe", "powershell", "pwsh"):
        path = shutil.which(name)
        if path:
            return path
    return None


def require_powershell() -> str:
    path = find_powershell()
    if path:
        return path
    raise YarkError(
        "powershell.exe not found. Run yark inside WSL (recommended) or install PowerShell."
    )


def parse_keys_line(line: str) -> set[str] | None:
    text = line.strip()
    if not text.startswith("YARK keys"):
        return None
    names = text[9:].strip().split()
    lowered = [name.lower() for name in names if name]
    return expand_tokens(lowered)


def host_script_path() -> Path:
    here = Path(__file__).with_name("win_host.ps1")
    if here.is_file():
        return here
    raise YarkError(f"missing Windows helper script: {here}")


def windows_path(path: Path) -> str:
    resolved = path.resolve()
    if running_in_wsl():
        wslpath = shutil.which("wslpath")
        if not wslpath:
            raise YarkError("wslpath not found; cannot translate WSL paths for powershell.exe")
        result = subprocess.run(
            [wslpath, "-w", str(resolved)],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    return str(resolved)


def _powershell_base() -> list[str]:
    return [
        require_powershell(),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
    ]


def inject_text(text: str, mode: str = "paste") -> None:
    if not text:
        return
    if mode == "print":
        print(text, end="", flush=True)
        return
    if mode not in {"paste", "unicode"}:
        raise YarkError(f"unknown inject mode {mode!r}; use paste or print on Windows")
    payload = base64.b64encode(text.encode("utf-16le")).decode("ascii")
    script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$bytes = [Convert]::FromBase64String('{payload}')
$value = [Text.Encoding]::Unicode.GetString($bytes)
$previous = $null
try {{ $previous = Get-Clipboard -Raw -ErrorAction SilentlyContinue }} catch {{}}
Set-Clipboard -Value $value
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 80
if ($null -ne $previous) {{ Set-Clipboard -Value $previous }}
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    subprocess.run(
        _powershell_base() + ["-STA", "-EncodedCommand", encoded],
        check=True,
        capture_output=True,
    )


def beep() -> None:
    try:
        script = "[console]::Beep(880, 70)"
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        subprocess.run(
            _powershell_base() + ["-EncodedCommand", encoded],
            check=False,
            capture_output=True,
            timeout=3,
        )
    except Exception:
        print("\a", end="", flush=True)


class WinHoldListener:
    """Hold-to-talk via a PowerShell GetAsyncKeyState poller."""

    def __init__(
        self,
        on_press: Callable[[str], None],
        on_release: Callable[[], None],
    ):
        self._machine = HoldMachine(on_press, on_release)
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def set_chords(self, chords: dict[str, str] | str) -> None:
        self._machine.set_chords(chords)

    def start(self, chords: dict[str, str] | str | None = None) -> None:
        self.stop()
        if chords is not None:
            self.set_chords(chords)
        if not self._machine.has_chords:
            return
        script = windows_path(host_script_path())
        self._stop.clear()
        self._proc = subprocess.Popen(
            _powershell_base() + ["-File", script, "-Mode", "keys"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._thread = threading.Thread(target=self._read, daemon=True, name="yark-win-keys")
        self._thread.start()
        logger.info("Windows hold-to-talk helper pid=%s", self._proc.pid)

    def restart(self, chords: dict[str, str] | str) -> None:
        self.start(chords)

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1)
        self._machine.reset(release=True)

    def _read(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in proc.stdout:
                if self._stop.is_set():
                    return
                tokens = parse_keys_line(raw)
                if tokens is None:
                    continue
                self._machine.sync(tokens)
        except Exception:
            logger.exception("Windows hotkey helper failed")


class WinMicrophone:
    """16 kHz PCM from the Windows default recording device, via PowerShell."""

    def __init__(self, sample_rate: int = 16000, chunk_ms: int = 200):
        self._sample_rate = sample_rate
        self._chunk_ms = chunk_ms
        self._proc: asyncio.subprocess.Process | None = None
        self._queue: asyncio.Queue[object] | None = None
        self._reader: asyncio.Task | None = None
        self._stopped = False

    async def __aenter__(self) -> "WinMicrophone":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    async def start(self) -> None:
        self._stopped = False
        self._queue = asyncio.Queue(maxsize=32)
        script = windows_path(host_script_path())
        logger.info(
            "Windows mic start rate=%s chunk_ms=%s",
            self._sample_rate,
            self._chunk_ms,
        )
        self._proc = await asyncio.create_subprocess_exec(
            *_powershell_base(),
            "-File",
            script,
            "-Mode",
            "mic",
            "-Rate",
            str(self._sample_rate),
            "-ChunkMs",
            str(self._chunk_ms),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader = asyncio.create_task(self._read(), name="yark-win-mic")

    async def chunks(self) -> AsyncIterator[bytes]:
        if self._queue is None:
            raise YarkError("Windows microphone is not started")
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                return
            yield item  # type: ignore[misc]

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        proc = self._proc
        self._proc = None
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        reader = self._reader
        self._reader = None
        if reader is not None and not reader.done():
            reader.cancel()
            try:
                await reader
            except (asyncio.CancelledError, Exception):
                pass
        if self._queue is not None:
            try:
                self._queue.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                pass

    async def _read(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text.startswith("YARK pcm "):
                    continue
                try:
                    pcm = base64.b64decode(text[9:].strip())
                except Exception:
                    continue
                if pcm and self._queue is not None:
                    try:
                        self._queue.put_nowait(pcm)
                    except asyncio.QueueFull:
                        try:
                            self._queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            self._queue.put_nowait(pcm)
                        except asyncio.QueueFull:
                            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Windows microphone helper failed")
        finally:
            if self._queue is not None:
                try:
                    self._queue.put_nowait(_SENTINEL)
                except asyncio.QueueFull:
                    pass


def linux_mic_available() -> bool:
    try:
        import sounddevice as sd

        for info in sd.query_devices():
            if info.get("max_input_channels", 0) > 0:
                return True
    except Exception:
        return False
    return False


def open_microphone(sample_rate: int, chunk_ms: int, device: str = ""):
    force_windows = device.strip().lower() in {"windows", "win", "wasapi"}
    if not force_windows and linux_mic_available():
        from yark.config import AudioConfig
        from yark.mic import Microphone

        return Microphone(AudioConfig(sample_rate=sample_rate, chunk_ms=chunk_ms, device=device))
    if not on_windows_host():
        raise YarkError(
            "no microphone found. In WSL, enable WSLg/PulseAudio or set "
            'audio.device = "windows" to use the Windows recording device.'
        )
    return WinMicrophone(sample_rate=sample_rate, chunk_ms=chunk_ms)


def doctor_lines() -> list[str]:
    rows = [
        f"host: {'WSL' if running_in_wsl() else ('Windows' if sys.platform == 'win32' else sys.platform)}"
    ]
    ps = find_powershell()
    rows.append(f"powershell: {ps or 'MISSING'}")
    clip = shutil.which("clip.exe") or shutil.which("clip")
    rows.append(f"clip.exe: {clip or '(not required; using Set-Clipboard)'}")
    try:
        rows.append(f"helper: {host_script_path()}")
    except YarkError as exc:
        rows.append(f"helper: MISSING ({exc})")
    rows.append(
        "linux mic: "
        + ("yes" if linux_mic_available() else "no (will use Windows recording device)")
    )
    rows.append("key map: option=Alt  command=Win  control=Ctrl")
    return rows
