import pytest

from yark.proxy import bypass_proxy, proxy_for_url, redact_proxy


def test_https_proxy_used_for_wss(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    assert (
        proxy_for_url("wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async")
        == "http://127.0.0.1:7890"
    )


def test_https_proxy_used_for_https_llm(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    for key in ("https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(key, raising=False)
    assert (
        proxy_for_url("https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        == "http://proxy.example:8080"
    )


def test_no_proxy_bypasses_host(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("NO_PROXY", "localhost,.bytedance.com")
    for key in ("https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "no_proxy"):
        monkeypatch.delenv(key, raising=False)
    assert proxy_for_url("wss://openspeech.bytedance.com/x") is None
    assert proxy_for_url("https://api.openai.com/v1") == "http://127.0.0.1:7890"


def test_bypass_proxy_star(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NO_PROXY", "*")
    assert bypass_proxy("example.com") is True


def test_redact_proxy_credentials():
    assert (
        redact_proxy("http://user:secret@127.0.0.1:7890") == "http://***@127.0.0.1:7890"
    )
    assert redact_proxy("http://127.0.0.1:7890") == "http://127.0.0.1:7890"
