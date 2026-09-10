"""Volcengine SAUC bigmodel WebSocket binary protocol.

Matches the official demo attached to
https://docs.volcengine.com/docs/6561/2630027
(双向流式语音识别WebSocket, wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async).
"""

from __future__ import annotations

import gzip
import json
import struct
from dataclasses import dataclass
from typing import Any


PROTOCOL_VERSION = 0b0001
HEADER_SIZE_UNITS = 1  # 1 * 4 bytes

MSG_FULL_CLIENT = 0b0001
MSG_AUDIO_ONLY = 0b0010
MSG_FULL_SERVER = 0b1001
MSG_SERVER_ERROR = 0b1111

FLAG_NO_SEQUENCE = 0b0000
FLAG_POS_SEQUENCE = 0b0001
FLAG_NEG_SEQUENCE = 0b0010  # last packet, no sequence field
FLAG_NEG_WITH_SEQUENCE = 0b0011  # last packet, sequence is negative

SERIAL_NONE = 0b0000
SERIAL_JSON = 0b0001
COMPRESS_NONE = 0b0000
COMPRESS_GZIP = 0b0001


def _header(message_type: int, flags: int, serialization: int, compression: int) -> bytes:
    return bytes(
        [
            (PROTOCOL_VERSION << 4) | HEADER_SIZE_UNITS,
            (message_type << 4) | flags,
            (serialization << 4) | compression,
            0x00,
        ]
    )


def encode_full_client_request(seq: int, payload: dict[str, Any]) -> bytes:
    """First packet: JSON config, gzip-compressed, positive sequence."""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    compressed = gzip.compress(raw)
    return (
        _header(MSG_FULL_CLIENT, FLAG_POS_SEQUENCE, SERIAL_JSON, COMPRESS_GZIP)
        + struct.pack(">i", seq)
        + struct.pack(">I", len(compressed))
        + compressed
    )


def encode_audio_only_request(seq: int, pcm: bytes, *, last: bool = False) -> bytes:
    """Subsequent packets: gzip-compressed PCM. Last packet uses negative seq."""
    if last:
        flags = FLAG_NEG_WITH_SEQUENCE
        wire_seq = -abs(seq) if seq != 0 else -1
    else:
        flags = FLAG_POS_SEQUENCE
        wire_seq = seq
    compressed = gzip.compress(pcm)
    return (
        _header(MSG_AUDIO_ONLY, flags, SERIAL_JSON, COMPRESS_GZIP)
        + struct.pack(">i", wire_seq)
        + struct.pack(">I", len(compressed))
        + compressed
    )


@dataclass
class ServerResponse:
    code: int = 0
    event: int = 0
    is_last_package: bool = False
    payload_sequence: int = 0
    payload_size: int = 0
    payload_msg: dict[str, Any] | None = None
    raw_message_type: int = 0

    def result(self) -> dict[str, Any]:
        msg = self.payload_msg or {}
        result = msg.get("result")
        if isinstance(result, list):
            return result[0] if result else {}
        if isinstance(result, dict):
            return result
        return {}

    def text(self) -> str:
        return str(self.result().get("text") or "")

    def utterances(self) -> list[dict[str, Any]]:
        items = self.result().get("utterances") or []
        return items if isinstance(items, list) else []


def parse_server_response(msg: bytes) -> ServerResponse:
    if len(msg) < 4:
        raise ValueError(f"ASR frame too short: {len(msg)} bytes")

    header_size = (msg[0] & 0x0F) * 4
    message_type = msg[1] >> 4
    flags = msg[1] & 0x0F
    serialization = msg[2] >> 4
    compression = msg[2] & 0x0F
    payload = msg[header_size:]

    response = ServerResponse(raw_message_type=message_type)

    if flags & 0x01:
        if len(payload) < 4:
            raise ValueError("truncated sequence field")
        response.payload_sequence = struct.unpack(">i", payload[:4])[0]
        payload = payload[4:]
    if flags & 0x02:
        response.is_last_package = True
    if flags & 0x04:
        if len(payload) < 4:
            raise ValueError("truncated event field")
        response.event = struct.unpack(">i", payload[:4])[0]
        payload = payload[4:]

    if message_type == MSG_FULL_SERVER:
        if len(payload) < 4:
            return response
        response.payload_size = struct.unpack(">I", payload[:4])[0]
        payload = payload[4:]
    elif message_type == MSG_SERVER_ERROR:
        if len(payload) < 8:
            raise ValueError("truncated error frame")
        response.code = struct.unpack(">i", payload[:4])[0]
        response.payload_size = struct.unpack(">I", payload[4:8])[0]
        payload = payload[8:]
    else:
        # Unknown type: still try to skip a size prefix if present.
        if len(payload) >= 4:
            response.payload_size = struct.unpack(">I", payload[:4])[0]
            payload = payload[4:]

    if not payload:
        return response

    if compression == COMPRESS_GZIP:
        payload = gzip.decompress(payload)

    if serialization == SERIAL_JSON:
        decoded = json.loads(payload.decode("utf-8"))
        if isinstance(decoded, dict):
            response.payload_msg = decoded
            if "code" in decoded and isinstance(decoded["code"], int) and response.code == 0:
                response.code = decoded["code"]
    return response


def default_request_payload(
    *,
    uid: str,
    sample_rate: int = 16000,
    bits: int = 16,
    channel: int = 1,
    enable_itn: bool = True,
    enable_punc: bool = True,
    enable_ddc: bool = True,
    show_utterances: bool = True,
    end_window_size: int = 800,
    result_type: str = "single",
    enable_nonstream: bool = False,
) -> dict[str, Any]:
    return {
        "user": {"uid": uid, "platform": "macOS", "app_version": "yark/0.1.0"},
        "audio": {
            "format": "pcm",
            "codec": "raw",
            "rate": sample_rate,
            "bits": bits,
            "channel": channel,
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": enable_itn,
            "enable_punc": enable_punc,
            "enable_ddc": enable_ddc,
            "show_utterances": show_utterances,
            "enable_nonstream": enable_nonstream,
            "result_type": result_type,
            "end_window_size": end_window_size,
        },
    }
