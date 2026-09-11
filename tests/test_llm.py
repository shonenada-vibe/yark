from yark.config import LlmConfig, LlmFeatureConfig
from yark.llm import ChatRequest, LlmPipeline, chat_completions_url, parse_chat_content


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
    assert fake.calls == []


def test_refine_then_translate_order():
    fake = FakeCompleter({"refine-me": "cleaned", "translate-me": "translated"})
    pipe = LlmPipeline(_cfg(refine=True, translate=True), fake)
    assert pipe.apply("raw text") == "translated"
    assert [c.prompt for c in fake.calls] == ["refine-me", "translate-me"]
    assert fake.calls[0].text == "raw text"
    assert fake.calls[1].text == "cleaned"
    assert fake.calls[0].api_key == "sk-shared"
    assert fake.calls[1].api_key == "sk-tr"


def test_llm_error_keeps_original_text():
    fake = FakeCompleter(error=RuntimeError("boom"))
    pipe = LlmPipeline(_cfg(refine=True), fake)
    assert pipe.apply("keep me") == "keep me"
    assert len(fake.calls) == 1
