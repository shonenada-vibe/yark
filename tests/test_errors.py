from yark.errors import AuthError, ConfigError, SttError, format_hud_error


def test_format_hud_error_auth():
    assert format_hud_error(AuthError("nope")) == "Volcengine authentication failed"


def test_format_hud_error_stt():
    assert format_hud_error(SttError("timed out waiting for ASR response (30s)")) == (
        "Speech recognition timed out"
    )
    assert format_hud_error(SttError("cannot reach wss://example")) == (
        "Cannot reach Volcengine"
    )
    assert format_hud_error(
        SttError("ASR error code=4500001 logid=abc payload={'msg': 'busy'}")
    ) == "Speech recognition error 4500001"


def test_format_hud_error_llm_and_action():
    exc = RuntimeError("LLM HTTP 403: {\"error\":{\"message\":\"banned\"}}")
    assert format_hud_error(exc) == "LLM HTTP 403"
    assert format_hud_error(exc, action="translate") == "Translate failed · LLM HTTP 403"


def test_format_hud_error_clips_long_text():
    msg = format_hud_error(ConfigError("x" * 120))
    assert len(msg) <= 72
    assert msg.endswith("…")
