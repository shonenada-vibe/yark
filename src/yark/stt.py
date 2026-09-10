"""Volcengine streaming ASR client."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator

import websockets
from websockets.exceptions import WebSocketException

from yark.config import AppConfig
from yark.errors import AuthError, SttError
from yark.protocol import (
    MSG_SERVER_ERROR,
    default_request_payload,
    encode_audio_only_request,
    encode_full_client_request,
    parse_server_response,
    ServerResponse,
)

logger = logging.getLogger("yark.stt")


class VolcengineStt:
    def __init__(self, cfg: AppConfig):
        self._cfg = cfg
        self._ws = None
        self._seq = 1
        self.request_id = str(uuid.uuid4())
        self.logid = ""

    async def __aenter__(self) -> "VolcengineStt":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        headers = self._cfg.volcengine.auth_headers(self.request_id)
        url = self._cfg.volcengine.endpoint
        logger.info("connecting %s request_id=%s", url, self.request_id)
        try:
            self._ws = await websockets.connect(
                url,
                additional_headers=headers,
                max_size=16 * 1024 * 1024,
                open_timeout=15,
                ping_interval=20,
                ping_timeout=20,
                proxy=None,
            )
        except WebSocketException as exc:
            text = str(exc)
            if any(code in text for code in ("401", "403", "Unauthorized")):
                raise AuthError(f"Volcengine handshake rejected: {exc}") from exc
            raise SttError(f"Volcengine handshake failed: {exc}") from exc
        except OSError as exc:
            raise SttError(f"cannot reach {url}: {exc}") from exc

        response_headers = getattr(self._ws, "response", None)
        if response_headers is not None:
            hdrs = getattr(response_headers, "headers", {})
            self.logid = hdrs.get("x-tt-logid") or hdrs.get("X-Tt-Logid") or ""
            if self.logid:
                logger.info("connected logid=%s", self.logid)

        payload = default_request_payload(
            uid=self.request_id,
            sample_rate=self._cfg.audio.sample_rate,
            enable_itn=self._cfg.stt.enable_itn,
            enable_punc=self._cfg.stt.enable_punc,
            enable_ddc=self._cfg.stt.enable_ddc,
            show_utterances=self._cfg.stt.show_utterances,
            end_window_size=self._cfg.stt.end_window_size,
            result_type=self._cfg.stt.result_type,
        )
        await self._send(encode_full_client_request(self._seq, payload))
        ack = await self.recv_one()
        if ack.code != 0:
            raise SttError(f"ASR init failed code={ack.code} payload={ack.payload_msg}")
        self._seq += 1
        logger.debug("init ack seq=%s", ack.payload_sequence)

    async def send_audio(self, pcm: bytes, *, last: bool = False) -> None:
        frame = encode_audio_only_request(self._seq, pcm, last=last)
        await self._send(frame)
        if not last:
            self._seq += 1

    async def recv_one(self, timeout: float = 15.0) -> ServerResponse:
        ws = self._require_ws()
        try:
            data = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise SttError(f"timed out waiting for ASR response ({timeout}s)") from exc
        except WebSocketException as exc:
            raise SttError(f"ASR connection closed: {exc}") from exc
        if isinstance(data, str):
            raise SttError(f"unexpected text frame from ASR: {data[:200]!r}")
        response = parse_server_response(data)
        if response.raw_message_type == MSG_SERVER_ERROR or response.code not in (0,):
            raise SttError(
                f"ASR error code={response.code} logid={self.logid} "
                f"payload={response.payload_msg}"
            )
        return response

    async def responses(self) -> AsyncIterator[ServerResponse]:
        while True:
            response = await self.recv_one(timeout=30.0)
            yield response
            if response.is_last_package:
                return

    async def close(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        try:
            await ws.close()
        except Exception:
            logger.debug("websocket close failed", exc_info=True)

    async def _send(self, frame: bytes) -> None:
        ws = self._require_ws()
        try:
            await ws.send(frame)
        except WebSocketException as exc:
            raise SttError(f"failed to send ASR frame: {exc}") from exc

    def _require_ws(self):
        if self._ws is None:
            raise SttError("ASR websocket is not connected")
        return self._ws
