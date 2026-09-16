from yark.hotkey import parse_hotkey
from yark.winbridge import host_script_path, parse_keys_line, running_in_wsl


def test_parse_keys_line():
    assert parse_keys_line("YARK keys") == set()
    tokens = parse_keys_line("YARK keys right_option")
    assert tokens is not None
    assert "right_option" in tokens
    assert "option" in tokens
    assert parse_keys_line("ready") is None


def test_windows_chords_match_macos_config_names():
    chord = parse_hotkey("command+option")
    tokens = parse_keys_line("YARK keys left_command right_option")
    assert tokens is not None
    assert chord.matches_tokens(tokens)
    assert parse_hotkey("right_option").matches_tokens(
        parse_keys_line("YARK keys right_option")
    )
    assert not parse_hotkey("right_option").matches_tokens(
        parse_keys_line("YARK keys left_option")
    )


def test_host_script_ships_with_package():
    path = host_script_path()
    text = path.read_text(encoding="utf-8")
    assert "YARK keys" in text
    assert "YARK pcm" in text
    assert "GetAsyncKeyState" in text


def test_running_in_wsl_false_outside_wsl(monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    monkeypatch.setattr("yark.winbridge.sys.platform", "darwin")
    assert running_in_wsl() is False
