from pathlib import Path

from yark.config import load_config, save_hotkey
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
