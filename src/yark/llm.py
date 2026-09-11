"""OpenAI-compatible post-process: refine, then translate, before typing."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin

from yark.config import LlmConfig, LlmFeatureConfig

logger = logging.getLogger("yark.llm")


@dataclass(frozen=True)
class ChatRequest:
    base_url: str
    api_key: str
    model: str
    prompt: str
    text: str
    timeout: float = 20.0


class Completer(Protocol):
    def complete(self, request: ChatRequest) -> str: ...


def chat_completions_url(base_url: str) -> str:
    base = base_url.strip() or "https://api.openai.com/v1"
    if not base.endswith("/"):
        base += "/"
    if base.endswith("/chat/completions/"):
        return base.rstrip("/")
    return urljoin(base, "chat/completions")


def parse_chat_content(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("chat completions response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ValueError("chat completions choice has no message")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("chat completions message has no text content")
    text = content.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


class HttpCompleter:
    def complete(self, request: ChatRequest) -> str:
        url = chat_completions_url(request.base_url)
        body = json.dumps(
            {
                "model": request.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": request.prompt},
                    {"role": "user", "content": request.text},
                ],
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if request.api_key:
            headers["Authorization"] = f"Bearer {request.api_key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=request.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("chat completions response is not an object")
        return parse_chat_content(payload)


class LlmPipeline:
    """Apply enabled refine then translate steps. Failures leave text unchanged."""

    def __init__(self, cfg: LlmConfig, completer: Completer | None = None):
        self._cfg = cfg
        self._completer = completer or HttpCompleter()

    def enabled(self) -> bool:
        return self._cfg.refine.enabled or self._cfg.translate.enabled

    def apply(self, text: str) -> str:
        if not text.strip() or not self.enabled():
            return text
        out = text
        out = self._run("refine", self._cfg.refine, out)
        out = self._run("translate", self._cfg.translate, out)
        return out

    def _run(self, name: str, feature: LlmFeatureConfig, text: str) -> str:
        if not feature.enabled:
            return text
        prompt = feature.prompt.strip()
        if not prompt:
            logger.warning("skip %s: empty prompt", name)
            return text
        request = ChatRequest(
            base_url=self._cfg.base_url,
            api_key=feature.api_key or self._cfg.api_key,
            model=self._cfg.model,
            prompt=prompt,
            text=text,
            timeout=self._cfg.timeout,
        )
        try:
            result = self._completer.complete(request).strip()
        except Exception:
            logger.exception("%s failed; typing original text", name)
            return text
        if not result:
            logger.warning("%s returned empty text; keeping original", name)
            return text
        logger.info("%s -> %r", name, result)
        return result
