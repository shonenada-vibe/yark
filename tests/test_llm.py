from yark.config import LlmConfig, LlmFeatureConfig
from yark.llm import (
    DEFAULT_USER_AGENT,
    ChatRequest,
    LlmPipeline,
    chat_completions_body,
    chat_completions_url,
    llm_http_headers,
    parse_chat_content,
)


class FakeCompleter:
    def __init__(self, replies: dict[str, str] | None = None, error: Exception | None = None):
        self.replies = replies or {}
        self.error = error
        self.calls: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> str:
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.replies.get(request.prompt, f"out:{request.text}")


def test_chat_completions_url():
    assert (
        chat_completions_url("https://api.openai.com/v1")
        == "https://api.openai.com/v1/chat/completions"
    )
    assert (
        chat_completions_url("https://api.openai.com/v1/")
        == "https://api.openai.com/v1/chat/completions"
    )
    assert (
        chat_completions_url("http://127.0.0.1:8000/v1/chat/completions")
        == "http://127.0.0.1:8000/v1/chat/completions"
    )


def test_chat_body_sets_reasoning_effort_none():
    body = chat_completions_body(
        ChatRequest(
            base_url="https://api.groq.com/openai/v1",
            api_key="sk",
            model="openai/gpt-oss-20b",
            prompt="sys",
            text="hi",
        )
    )
    assert body["reasoning_effort"] == "none"
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["messages"][1]["content"] == "hi"


def test_llm_headers_are_not_python_urllib(monkeypatch):
    monkeypatch.delenv("YARK_LLM_USER_AGENT", raising=False)
    headers = llm_http_headers("sk-test")
    assert headers["Authorization"] == "Bearer sk-test"
    assert "Python-urllib" not in headers["User-Agent"]
    assert headers["User-Agent"] == DEFAULT_USER_AGENT
    monkeypatch.setenv("YARK_LLM_USER_AGENT", "yark-test/1")
    assert llm_http_headers("").get("Authorization") is None
    assert llm_http_headers("")["User-Agent"] == "yark-test/1"


def test_parse_chat_content_strips_quotes():
    payload = {"choices": [{"message": {"content": '"Hello there."'}}]}
    assert parse_chat_content(payload) == "Hello there."


def _cfg(*, refine=False, translate=False, shared_key="sk-shared") -> LlmConfig:
    return LlmConfig(
        api_key=shared_key,
        refine=LlmFeatureConfig(enabled=refine, prompt="refine-me", api_key=""),
        translate=LlmFeatureConfig(enabled=translate, prompt="translate-me", api_key="sk-tr"),
    )


def test_disabled_pipeline_is_passthrough():
    fake = FakeCompleter()
    pipe = LlmPipeline(_cfg(), fake)
    assert pipe.apply("hello") == "hello"
    assert pipe.apply("hello", mode="transcript") == "hello"
    assert fake.calls == []


def test_translate_mode_only_translates():
    fake = FakeCompleter({"translate-me": "translated"})
    pipe = LlmPipeline(_cfg(translate=True), fake)
    assert pipe.apply("raw text", mode="translate") == "translated"
    assert [c.prompt for c in fake.calls] == ["translate-me"]
    assert fake.calls[0].api_key == "sk-tr"


def test_refine_mode_translates_then_refines():
    fake = FakeCompleter({"translate-me": "translated", "refine-me": "polished"})
    pipe = LlmPipeline(_cfg(refine=True, translate=True), fake)
    assert pipe.apply("raw text", mode="refine") == "polished"
    assert [c.prompt for c in fake.calls] == ["translate-me", "refine-me"]
    assert fake.calls[0].text == "raw text"
    assert fake.calls[1].text == "translated"


def test_llm_error_keeps_original_text():
    fake = FakeCompleter(error=RuntimeError("boom"))
    pipe = LlmPipeline(_cfg(refine=True), fake)
    assert pipe.apply("keep me", mode="translate") == "keep me"
    assert len(fake.calls) == 1
