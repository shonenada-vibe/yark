from pathlib import Path

from yark.config import load_config
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
