"""OpenAI-compatible post-process: refine, then translate, before typing."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin

from yark.config import LlmConfig, LlmFeatureConfig
from yark.proxy import proxy_for_url, redact_proxy

logger = logging.getLogger("yark.llm")

# Cloudflare (api.groq.com and others) returns 1010 if the client looks like
# Python-urllib. A browser-like UA is enough for Groq's bot score.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


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


def chat_completions_body(request: ChatRequest) -> dict:
    return {
        "model": request.model,
        "temperature": 0.2,
        "reasoning_effort": "none",
        "messages": [
            {"role": "system", "content": request.prompt},
            {"role": "user", "content": request.text},
        ],
    }


def llm_http_headers(api_key: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": os.environ.get("YARK_LLM_USER_AGENT") or DEFAULT_USER_AGENT,
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


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


def _urlopen(req: urllib.request.Request, timeout: float):
    url = req.full_url
    proxy = proxy_for_url(url)
    if proxy:
        logger.info("LLM via proxy %s", redact_proxy(proxy))
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


class HttpCompleter:
    def complete(self, request: ChatRequest) -> str:
        url = chat_completions_url(request.base_url)
        body = json.dumps(chat_completions_body(request)).encode("utf-8")
        headers = llm_http_headers(request.api_key)
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with _urlopen(req, timeout=request.timeout) as resp:
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

    def enabled(self, mode: str = "transcript") -> bool:
        return mode in {"translate", "refine"}

    def apply(self, text: str, mode: str = "transcript") -> str:
        if not text.strip() or not self.enabled(mode):
            return text
        out = text
        if mode in {"translate", "refine"}:
            out = self._run("translate", self._cfg.translate, out)
        if mode == "refine":
            out = self._run("refine", self._cfg.refine, out)
        return out

    def _run(self, name: str, feature: LlmFeatureConfig, text: str) -> str:
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
