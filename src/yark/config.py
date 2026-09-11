from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from yark.errors import ConfigError

DEFAULT_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
DEFAULT_RESOURCE_ID = "volc.seedasr.sauc.duration"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_REFINE_PROMPT = (
    "You clean up a speech-to-text transcript. Fix recognition mistakes, "
    "remove filler (um, uh, 那个, 就是), and keep the speaker's meaning and language. "
    "Do not add information. Output only the cleaned text."
)
DEFAULT_TRANSLATE_PROMPT = (
    "Translate the text to English. Keep names, numbers, and code unchanged. "
    "Output only the translation, with no quotes or notes."
)
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
    hotkey_transcript: str = "right_option"
    hotkey_translate: str = "command+option"
    hotkey_refine: str = "command+shift+option"
    inject: str = "unicode"
    beep: bool = True

    def hotkey_map(self) -> dict[str, str]:
        mapping = {
            "transcript": self.hotkey_transcript or self.hotkey,
            "translate": self.hotkey_translate,
            "refine": self.hotkey_refine,
        }
        return {name: spec for name, spec in mapping.items() if spec.strip()}


@dataclass(frozen=True)
class SttConfig:
    enable_itn: bool = True
    enable_punc: bool = True
    enable_ddc: bool = True
    show_utterances: bool = True
    end_window_size: int = 800
    result_type: str = "single"


@dataclass(frozen=True)
class LlmFeatureConfig:
    enabled: bool = False
    api_key: str = ""
    prompt: str = ""


@dataclass(frozen=True)
class LlmConfig:
    base_url: str = DEFAULT_LLM_BASE_URL
    model: str = DEFAULT_LLM_MODEL
    api_key: str = ""
    timeout: float = 20.0
    refine: LlmFeatureConfig = field(
        default_factory=lambda: LlmFeatureConfig(prompt=DEFAULT_REFINE_PROMPT)
    )
    translate: LlmFeatureConfig = field(
        default_factory=lambda: LlmFeatureConfig(prompt=DEFAULT_TRANSLATE_PROMPT)
    )

    def feature_key(self, feature: LlmFeatureConfig) -> str:
        return feature.api_key or self.api_key


@dataclass(frozen=True)
class AppConfig:
    volcengine: VolcengineConfig = field(default_factory=VolcengineConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    input: InputConfig = field(default_factory=InputConfig)
    stt: SttConfig = field(default_factory=SttConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
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
    llm_data = data.get("llm") or {}
    refine = llm_data.get("refine") or {}
    translate = llm_data.get("translate") or {}

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
            hotkey=str(inp.get("hotkey_transcript") or inp.get("hotkey") or "right_option"),
            hotkey_transcript=str(
                inp.get("hotkey_transcript") or inp.get("hotkey") or "right_option"
            ),
            hotkey_translate=_optional_hotkey(inp, "hotkey_translate", "command+option"),
            hotkey_refine=_optional_hotkey(inp, "hotkey_refine", "command+shift+option"),
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
        llm=LlmConfig(
            base_url=str(llm_data.get("base_url") or DEFAULT_LLM_BASE_URL),
            model=str(llm_data.get("model") or DEFAULT_LLM_MODEL),
            api_key=str(llm_data.get("api_key") or ""),
            timeout=float(llm_data.get("timeout") or 20),
            refine=_feature_from_table(refine, DEFAULT_REFINE_PROMPT),
            translate=_feature_from_table(translate, DEFAULT_TRANSLATE_PROMPT),
        ),
        path=used,
    )
    return _apply_env(cfg)


def _optional_hotkey(inp: dict, key: str, default: str) -> str:
    """Keep existing configs from inheriting new default chords they did not set."""
    if key in inp:
        return str(inp.get(key) or "")
    if inp:
        return ""
    return default


def _feature_from_table(data: dict, default_prompt: str) -> LlmFeatureConfig:
    return LlmFeatureConfig(
        enabled=_bool(data.get("enabled"), False),
        api_key=str(data.get("api_key") or ""),
        prompt=str(data.get("prompt") or default_prompt),
    )


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
    llm_key = os.environ.get("YARK_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    llm_base = os.environ.get("YARK_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    llm_model = os.environ.get("YARK_LLM_MODEL")

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
        inp_updates["hotkey_transcript"] = hotkey
    if inject:
        inp_updates["inject"] = inject
    if inp_updates:
        inp = replace(inp, **inp_updates)

    llm = cfg.llm
    llm_updates = {}
    if llm_key:
        llm_updates["api_key"] = llm_key
    if llm_base:
        llm_updates["base_url"] = llm_base
    if llm_model:
        llm_updates["model"] = llm_model
    if llm_updates:
        llm = replace(llm, **llm_updates)

    return replace(cfg, volcengine=volc, input=inp, llm=llm)


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
# Hold-to-talk shortcuts. Record them in Settings.
#   transcript = STT only
#   translate  = STT + translate
#   refine     = STT + translate + refine
hotkey = "right_option"
hotkey_transcript = "right_option"
hotkey_translate = "command+option"
hotkey_refine = "command+shift+option"
inject = "unicode"
beep = true

[stt]
enable_itn = true
enable_punc = true
enable_ddc = true
show_utterances = true
end_window_size = 800
result_type = "single"

[llm]
# OpenAI-compatible Chat Completions endpoint ( Groq, Together, local vLLM, … )
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
api_key = ""
timeout = 20.0

[llm.refine]
enabled = false
api_key = ""
prompt = "You clean up a speech-to-text transcript. Fix recognition mistakes, remove filler (um, uh, 那个, 就是), and keep the speaker's meaning and language. Do not add information. Output only the cleaned text."

[llm.translate]
enabled = false
api_key = ""
prompt = "Translate the text to English. Keep names, numbers, and code unchanged. Output only the translation, with no quotes or notes."
"""


def write_example_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_EXAMPLE_TOML, encoding="utf-8")


def config_path_for_write(cfg: AppConfig) -> Path:
    return cfg.path or USER_CONFIG_PATH


def save_llm_config(path: Path, llm: LlmConfig) -> Path:
    """Write the [llm] tables, creating the file if needed."""
    import tomlkit

    if not path.exists():
        write_example_config(path)
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    table = doc.get("llm")
    if table is None or not hasattr(table, "items"):
        table = tomlkit.table()
        doc["llm"] = table
    table["base_url"] = llm.base_url
    table["model"] = llm.model
    table["api_key"] = llm.api_key
    table["timeout"] = llm.timeout
    _write_feature_table(table, "refine", llm.refine)
    _write_feature_table(table, "translate", llm.translate)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return path


def _write_feature_table(parent, name: str, feature: LlmFeatureConfig) -> None:
    import tomlkit

    child = parent.get(name)
    if child is None or not hasattr(child, "items"):
        child = tomlkit.table()
        parent[name] = child
    child["enabled"] = bool(feature.enabled)
    child["api_key"] = feature.api_key
    child["prompt"] = feature.prompt


def save_hotkey(path: Path, hotkey: str, key: str = "hotkey") -> Path:
    """Set an `input` hotkey field in a TOML file, preserving comments when possible."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", key):
        raise ConfigError(f"invalid hotkey field {key!r}")
    if not re.fullmatch(r"[A-Za-z0-9_+]+", hotkey):
        raise ConfigError(f"invalid hotkey name {hotkey!r}")
    if not path.exists():
        write_example_config(path)
    text = path.read_text(encoding="utf-8")
    text = _replace_toml_string(text, key, hotkey)
    if key == "hotkey_transcript":
        text = _replace_toml_string(text, "hotkey", hotkey)
    path.write_text(text, encoding="utf-8")
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
