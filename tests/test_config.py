from pathlib import Path

from yark.config import (
    LlmConfig,
    LlmFeatureConfig,
    load_config,
    save_hotkey,
    save_llm_config,
)
from yark.errors import ConfigError
import pytest


def test_load_toml_and_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[volcengine]
api_key = "file-key"
resource_id = "volc.seedasr.sauc.duration"

[input]
hotkey = "f8"
inject = "paste"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("YARK_VOLC_API_KEY", "env-key")
    monkeypatch.setenv("YARK_HOTKEY", "right_option")
    cfg = load_config(path)
    assert cfg.volcengine.api_key == "env-key"
    assert cfg.input.hotkey == "right_option"
    assert cfg.input.inject == "paste"
    headers = cfg.volcengine.auth_headers("req-1")
    assert headers["X-Api-Key"] == "env-key"
    assert headers["X-Api-Resource-Id"] == "volc.seedasr.sauc.duration"
    assert headers["X-Api-Request-Id"] == "req-1"


def test_legacy_auth_headers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for key in ("YARK_VOLC_API_KEY", "VOLCENGINE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "config.toml"
    path.write_text(
        """
[volcengine]
app_key = "app"
access_key = "token"
""",
        encoding="utf-8",
    )
    cfg = load_config(path)
    headers = cfg.volcengine.auth_headers("x")
    assert headers["X-Api-App-Key"] == "app"
    assert headers["X-Api-Access-Key"] == "token"
    assert "X-Api-Key" not in headers


def test_missing_auth_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for key in (
        "YARK_VOLC_API_KEY",
        "VOLCENGINE_API_KEY",
        "YARK_VOLC_APP_KEY",
        "YARK_VOLC_ACCESS_KEY",
        "VOLCENGINE_APP_ID",
        "VOLCENGINE_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "config.toml"
    path.write_text("[volcengine]\napi_key = \"\"\n", encoding="utf-8")
    cfg = load_config(path)
    with pytest.raises(ConfigError):
        cfg.volcengine.auth_headers("x")


def test_save_hotkey_preserves_comments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for key in ("YARK_HOTKEY",):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "config.toml"
    path.write_text(
        """# keep this comment
[input]
hotkey = "f8"
inject = "paste"
""",
        encoding="utf-8",
    )
    save_hotkey(path, "right_option")
    text = path.read_text(encoding="utf-8")
    assert "# keep this comment" in text
    assert 'hotkey = "right_option"' in text
    assert 'inject = "paste"' in text
    cfg = load_config(path)
    assert cfg.input.hotkey == "right_option"


def test_save_hotkey_adds_input_section(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("[volcengine]\napi_key = \"x\"\n", encoding="utf-8")
    save_hotkey(path, "f13")
    text = path.read_text(encoding="utf-8")
    assert "[input]" in text
    assert 'hotkey = "f13"' in text


def test_save_hotkey_rejects_garbage():
    with pytest.raises(ConfigError):
        save_hotkey(Path("/tmp/unused.toml"), 'f8"\napi_key = "stolen')


def test_save_hotkey_allows_chords(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("[input]\nhotkey = \"f8\"\n", encoding="utf-8")
    save_hotkey(path, "command+option")
    text = path.read_text(encoding="utf-8")
    assert 'hotkey = "command+option"' in text


def test_load_llm_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for key in ("YARK_LLM_API_KEY", "OPENAI_API_KEY", "YARK_LLM_BASE_URL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "config.toml"
    path.write_text(
        """
[llm]
base_url = "http://127.0.0.1:11434/v1"
model = "local-model"
api_key = "shared-key"

[llm.refine]
enabled = true
api_key = "refine-key"
prompt = "clean it"

[llm.translate]
enabled = false
prompt = "to french"
""",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.llm.base_url == "http://127.0.0.1:11434/v1"
    assert cfg.llm.model == "local-model"
    assert cfg.llm.api_key == "shared-key"
    assert cfg.llm.refine.enabled is True
    assert cfg.llm.refine.api_key == "refine-key"
    assert cfg.llm.refine.prompt == "clean it"
    assert cfg.llm.translate.enabled is False
    assert cfg.llm.translate.prompt == "to french"
    assert cfg.llm.feature_key(cfg.llm.refine) == "refine-key"
    assert cfg.llm.feature_key(cfg.llm.translate) == "shared-key"


def test_save_llm_config_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for key in ("YARK_LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "config.toml"
    path.write_text("[input]\nhotkey = \"f8\"\n", encoding="utf-8")
    llm = LlmConfig(
        base_url="https://example.com/v1",
        model="gpt-test",
        api_key="sk-1",
        refine=LlmFeatureConfig(enabled=True, api_key="sk-r", prompt="fix words"),
        translate=LlmFeatureConfig(enabled=True, api_key="", prompt="to en"),
    )
    save_llm_config(path, llm)
    cfg = load_config(path)
    assert cfg.input.hotkey == "f8"
    assert cfg.llm.base_url == "https://example.com/v1"
    assert cfg.llm.refine.enabled is True
    assert cfg.llm.refine.prompt == "fix words"
    assert cfg.llm.translate.enabled is True
    assert cfg.llm.translate.prompt == "to en"
