from yark.protocol import ServerResponse
from yark.transcript import TranscriptCommitter


def _resp(*, text="", utterances=None, last=False) -> ServerResponse:
    return ServerResponse(
        is_last_package=last,
        payload_msg={
            "result": {
                "text": text,
                "utterances": utterances or [],
            }
        },
    )


def test_commits_definite_utterance_once():
    c = TranscriptCommitter()
    utt = {"definite": True, "start_time": 0, "text": "你好"}
    assert c.feed(_resp(text="你好", utterances=[utt])) == ["你好"]
    assert c.feed(_resp(text="你好", utterances=[utt])) == []


def test_ignores_partial_until_definite_or_last():
    c = TranscriptCommitter()
    growing = {"definite": False, "start_time": 10, "text": "今"}
    assert c.feed(_resp(text="今", utterances=[growing])) == []
    growing = {"definite": False, "start_time": 10, "text": "今天"}
    assert c.feed(_resp(text="今天", utterances=[growing])) == []
    done = {"definite": True, "start_time": 10, "text": "今天天气不错"}
    assert c.feed(_resp(text="今天天气不错", utterances=[done])) == ["今天天气不错"]


def test_last_package_flushes_indefinite_text():
    c = TranscriptCommitter()
    utt = {"definite": False, "start_time": 0, "text": "还没说完"}
    assert c.feed(_resp(text="还没说完", utterances=[utt], last=True)) == ["还没说完"]


def test_full_mode_replays_do_not_retype():
    c = TranscriptCommitter()
    first = {"definite": True, "start_time": 0, "text": "第一句。"}
    second_partial = {"definite": False, "start_time": 900, "text": "第"}
    assert c.feed(_resp(text="第一句。第", utterances=[first, second_partial])) == ["第一句。"]
    second = {"definite": True, "start_time": 900, "text": "第二句。"}
    assert c.feed(_resp(text="第一句。第二句。", utterances=[first, second])) == ["第二句。"]


def test_english_inserts_space_between_alnum():
    c = TranscriptCommitter()
    a = {"definite": True, "start_time": 0, "text": "Hello"}
    b = {"definite": True, "start_time": 400, "text": "world"}
    assert c.feed(_resp(utterances=[a])) == ["Hello"]
    assert c.feed(_resp(utterances=[a, b])) == [" world"]
