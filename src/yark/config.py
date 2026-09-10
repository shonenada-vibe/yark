from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from yark.errors import ConfigError

DEFAULT_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
DEFAULT_RESOURCE_ID = "volc.seedasr.sauc.duration"
USER_CONFIG_PATH = Path.home() / ".config" / "yark" / "config.toml"
CONFIG_PATHS = (
    Path("config.toml"),
    USER_CONFIG_PATH,
)


@dataclass(frozen=True)
class VolcengineConfig:
    api_key: str = ""
    app_key: str = ""
    access_key: str = ""
    resource_id: str = DEFAULT_RESOURCE_ID
    endpoint: str = DEFAULT_ENDPOINT

    def auth_headers(self, request_id: str) -> dict[str, str]:
        headers = {
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Connect-Id": request_id,
        }
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        elif self.app_key and self.access_key:
            headers["X-Api-App-Key"] = self.app_key
            headers["X-Api-Access-Key"] = self.access_key
        else:
            raise ConfigError(
                "Volcengine auth is missing. Set api_key (new console) or "
                "app_key + access_key (legacy console) in ~/.config/yark/config.toml "
                "or export YARK_VOLC_API_KEY."
            )
        return headers

    def redacted(self) -> str:
        def mask(value: str) -> str:
            if not value:
                return "(empty)"
            if len(value) <= 8:
                return value[:2] + "…"
            return value[:4] + "…" + value[-4:]

        if self.api_key:
            auth = f"api_key={mask(self.api_key)}"
        elif self.app_key:
            auth = f"app_key={mask(self.app_key)} access_key={mask(self.access_key)}"
        else:
            auth = "auth=(missing)"
        return f"{auth} resource_id={self.resource_id}"


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int = 16000
    chunk_ms: int = 200
    device: str = ""

    @property
    def chunk_bytes(self) -> int:
        return self.sample_rate * 2 * self.chunk_ms // 1000


@dataclass(frozen=True)
class InputConfig:
    hotkey: str = "right_option"
    inject: str = "unicode"
    beep: bool = True


@dataclass(frozen=True)
class SttConfig:
    enable_itn: bool = True
    enable_punc: bool = True
    enable_ddc: bool = True
    show_utterances: bool = True
    end_window_size: int = 800
    result_type: str = "single"


@dataclass(frozen=True)
class AppConfig:
    volcengine: VolcengineConfig = field(default_factory=VolcengineConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    input: InputConfig = field(default_factory=InputConfig)
    stt: SttConfig = field(default_factory=SttConfig)
    path: Path | None = None


def load_config(path: Path | None = None) -> AppConfig:
    data: dict = {}
    used: Path | None = path
    if path is not None:
        data = _read_toml(path)
    else:
        for candidate in CONFIG_PATHS:
            if candidate.exists():
                data = _read_toml(candidate)
                used = candidate
                break

    volc = data.get("volcengine") or {}
    audio = data.get("audio") or {}
    inp = data.get("input") or {}
    stt = data.get("stt") or {}

    cfg = AppConfig(
        volcengine=VolcengineConfig(
            api_key=str(volc.get("api_key") or ""),
            app_key=str(volc.get("app_key") or ""),
            access_key=str(volc.get("access_key") or ""),
            resource_id=str(volc.get("resource_id") or DEFAULT_RESOURCE_ID),
            endpoint=str(volc.get("endpoint") or DEFAULT_ENDPOINT),
        ),
        audio=AudioConfig(
            sample_rate=int(audio.get("sample_rate") or 16000),
            chunk_ms=int(audio.get("chunk_ms") or 200),
            device=str(audio.get("device") or ""),
        ),
        input=InputConfig(
            hotkey=str(inp.get("hotkey") or "right_option"),
            inject=str(inp.get("inject") or "unicode"),
            beep=bool(inp.get("beep") if "beep" in inp else True),
        ),
        stt=SttConfig(
            enable_itn=_bool(stt.get("enable_itn"), True),
            enable_punc=_bool(stt.get("enable_punc"), True),
            enable_ddc=_bool(stt.get("enable_ddc"), True),
            show_utterances=_bool(stt.get("show_utterances"), True),
            end_window_size=int(stt.get("end_window_size") or 800),
            result_type=str(stt.get("result_type") or "single"),
        ),
        path=used,
    )
    return _apply_env(cfg)


def _apply_env(cfg: AppConfig) -> AppConfig:
    api_key = os.environ.get("YARK_VOLC_API_KEY") or os.environ.get("VOLCENGINE_API_KEY")
    app_key = os.environ.get("YARK_VOLC_APP_KEY") or os.environ.get("VOLCENGINE_APP_ID")
    access_key = os.environ.get("YARK_VOLC_ACCESS_KEY") or os.environ.get(
        "VOLCENGINE_ACCESS_TOKEN"
    )
    resource_id = os.environ.get("YARK_VOLC_RESOURCE_ID")
    endpoint = os.environ.get("YARK_VOLC_ENDPOINT")
    hotkey = os.environ.get("YARK_HOTKEY")
    inject = os.environ.get("YARK_INJECT")

    volc = cfg.volcengine
    updates = {}
    if api_key:
        updates["api_key"] = api_key
    if app_key:
        updates["app_key"] = app_key
    if access_key:
        updates["access_key"] = access_key
    if resource_id:
        updates["resource_id"] = resource_id
    if endpoint:
        updates["endpoint"] = endpoint
    if updates:
        volc = replace(volc, **updates)

    inp = cfg.input
    inp_updates = {}
    if hotkey:
        inp_updates["hotkey"] = hotkey
    if inject:
        inp_updates["inject"] = inject
    if inp_updates:
        inp = replace(inp, **inp_updates)

    return replace(cfg, volcengine=volc, input=inp)


_EXAMPLE_TOML = """\
# Copy to ~/.config/yark/config.toml (or ./config.toml).
# Environment variables override these values.

[volcengine]
# New console: API Key from
# https://console.volcengine.com/speech/new/setting/apikeys
api_key = ""

# Legacy console (used only when api_key is empty):
app_key = ""
access_key = ""

# Seed-ASR 2.0 duration (recommended). Alternatives:
#   volc.seedasr.sauc.concurrent
#   volc.bigasr.sauc.duration
#   volc.bigasr.sauc.concurrent
resource_id = "volc.seedasr.sauc.duration"

# Bidirectional streaming (optimized). Other endpoints:
#   wss://openspeech.bytedance.com/api/v3/sauc/bigmodel
#   wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream
endpoint = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"

[audio]
sample_rate = 16000
chunk_ms = 200
device = ""

[input]
hotkey = "right_option"
inject = "unicode"
beep = true

[stt]
enable_itn = true
enable_punc = true
enable_ddc = true
show_utterances = true
end_window_size = 800
result_type = "single"
"""


def write_example_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_EXAMPLE_TOML, encoding="utf-8")


def config_path_for_write(cfg: AppConfig) -> Path:
    return cfg.path or USER_CONFIG_PATH


def save_hotkey(path: Path, hotkey: str) -> Path:
    """Set `input.hotkey` in a TOML file, preserving comments when possible."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", hotkey):
        raise ConfigError(f"invalid hotkey name {hotkey!r}")
    if not path.exists():
        write_example_config(path)
    text = path.read_text(encoding="utf-8")
    path.write_text(_replace_toml_string(text, "hotkey", hotkey), encoding="utf-8")
    return path


def _replace_toml_string(text: str, key: str, value: str) -> str:
    pattern = rf'(?m)^({re.escape(key)}\s*=\s*)(["\']).*?\2'
    if re.search(pattern, text):
        return re.sub(pattern, rf'\1"{value}"', text, count=1)
    if re.search(r"(?m)^\[input\]\s*$", text):
        return re.sub(
            r"(?m)^(\[input\]\s*\n)",
            rf'\1{key} = "{value}"\n',
            text,
            count=1,
        )
    return text.rstrip() + f'\n\n[input]\n{key} = "{value}"\n'


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config {path} is not a table")
    return data


def _bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
