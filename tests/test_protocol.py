import gzip
import json
import struct

from yark.protocol import (
    FLAG_NEG_WITH_SEQUENCE,
    FLAG_POS_SEQUENCE,
    MSG_AUDIO_ONLY,
    MSG_FULL_CLIENT,
    MSG_FULL_SERVER,
    MSG_SERVER_ERROR,
    default_request_payload,
    encode_audio_only_request,
    encode_full_client_request,
    parse_server_response,
)


def test_full_client_request_roundtrip_payload():
    payload = {"user": {"uid": "u1"}, "audio": {"format": "pcm", "rate": 16000}}
    frame = encode_full_client_request(1, payload)
    assert frame[0] >> 4 == 1
    assert frame[1] >> 4 == MSG_FULL_CLIENT
    assert frame[1] & 0x0F == FLAG_POS_SEQUENCE
    seq = struct.unpack(">i", frame[4:8])[0]
    size = struct.unpack(">I", frame[8:12])[0]
    assert seq == 1
    body = gzip.decompress(frame[12 : 12 + size])
    assert json.loads(body) == payload


def test_last_audio_packet_uses_negative_sequence():
    pcm = b"\x00\x01" * 16
    frame = encode_audio_only_request(7, pcm, last=True)
    assert frame[1] >> 4 == MSG_AUDIO_ONLY
    assert frame[1] & 0x0F == FLAG_NEG_WITH_SEQUENCE
    seq = struct.unpack(">i", frame[4:8])[0]
    assert seq == -7
    size = struct.unpack(">I", frame[8:12])[0]
    assert gzip.decompress(frame[12 : 12 + size]) == pcm


def test_parse_gzip_json_server_response():
    body = {
        "audio_info": {"duration": 1200},
        "result": {
            "text": "打开客厅空调",
            "utterances": [
                {"definite": True, "start_time": 120, "end_time": 800, "text": "打开客厅空调"}
            ],
        },
    }
    compressed = gzip.compress(json.dumps(body).encode("utf-8"))
    frame = (
        bytes([(1 << 4) | 1, (MSG_FULL_SERVER << 4) | FLAG_POS_SEQUENCE, (1 << 4) | 1, 0])
        + struct.pack(">i", 4)
        + struct.pack(">I", len(compressed))
        + compressed
    )
    parsed = parse_server_response(frame)
    assert parsed.code == 0
    assert parsed.payload_sequence == 4
    assert parsed.is_last_package is False
    assert parsed.text() == "打开客厅空调"
    assert parsed.utterances()[0]["definite"] is True


def test_parse_last_package_and_error():
    last = bytes([(1 << 4) | 1, (MSG_FULL_SERVER << 4) | 0b0011, (1 << 4) | 0, 0])
    last += struct.pack(">i", -9) + struct.pack(">I", 0)
    parsed = parse_server_response(last)
    assert parsed.is_last_package is True
    assert parsed.payload_sequence == -9

    err_msg = gzip.compress(b'{"error":"bad"}')
    err = (
        bytes([(1 << 4) | 1, (MSG_SERVER_ERROR << 4) | 0, (1 << 4) | 1, 0])
        + struct.pack(">i", 45000001)
        + struct.pack(">I", len(err_msg))
        + err_msg
    )
    parsed_err = parse_server_response(err)
    assert parsed_err.code == 45000001
    assert parsed_err.payload_msg == {"error": "bad"}


def test_default_request_payload_is_pcm16k():
    payload = default_request_payload(uid="abc")
    assert payload["audio"]["format"] == "pcm"
    assert payload["audio"]["rate"] == 16000
    assert payload["request"]["model_name"] == "bigmodel"
    assert payload["request"]["show_utterances"] is True
