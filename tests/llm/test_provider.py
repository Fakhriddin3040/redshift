import json

import httpx
import pytest

from vigil.llm import provider as provider_module
from vigil.llm.config import LLMSettings
from vigil.llm.provider import LLMError, OpenAICompatibleProvider, create_provider

MESSAGES = [{"role": "user", "content": "hi"}]


def settings(**kw) -> LLMSettings:
    base = dict(base_url="https://llm.test/v1", api_key="secret", model="some-model",
                timeout=5, max_retries=2)  # fmt: skip
    return LLMSettings(_env_file=None, **(base | kw))


def reply(text: str = "hello") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def make(handler, **kw) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(settings(**kw), httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr(provider_module.asyncio, "sleep", instant)


async def test_request_is_built_only_from_settings():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return reply("  the answer \n")

    p = make(handler, model="other-model", base_url="https://elsewhere.test/api/v1/")
    assert await p.chat(MESSAGES) == "the answer"
    assert seen["url"] == "https://elsewhere.test/api/v1/chat/completions"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"]["model"] == "other-model"
    assert seen["body"]["messages"] == MESSAGES


async def test_no_auth_header_without_a_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return reply()

    await make(handler, api_key="").chat(MESSAGES)
    assert seen["auth"] is None


async def test_retries_on_server_errors_and_timeouts_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, text="busy")
        if len(calls) == 2:
            raise httpx.ReadTimeout("slow", request=request)
        return reply("ok")

    assert await make(handler).chat(MESSAGES) == "ok"
    assert len(calls) == 3


async def test_gives_up_after_max_retries():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "1"}, text="slow down")

    with pytest.raises(LLMError, match="429"):
        await make(handler, max_retries=2).chat(MESSAGES)
    assert len(calls) == 3  # the first attempt + 2 retries


async def test_client_errors_are_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, text="bad key")

    with pytest.raises(LLMError, match="401"):
        await make(handler).chat(MESSAGES)
    assert len(calls) == 1


async def test_malformed_or_empty_reply_is_an_error():
    with pytest.raises(LLMError):
        await make(lambda r: httpx.Response(200, json={"unexpected": True})).chat(
            MESSAGES
        )
    with pytest.raises(LLMError):
        await make(lambda r: reply("   ")).chat(MESSAGES)


def test_llm_is_off_unless_url_and_model_are_set():
    assert create_provider(settings(base_url="")) is None
    assert create_provider(settings(model="")) is None
    assert not LLMSettings(_env_file=None).enabled


def test_settings_come_from_the_environment(monkeypatch):
    for key, value in {"LLM_BASE_URL": "https://x.test/v1", "LLM_API_KEY": "k",
                       "LLM_MODEL": "m", "LLM_TIMEOUT": "7", "LLM_MAX_RETRIES": "1"}.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    s = LLMSettings(_env_file=None)
    assert (s.base_url, s.api_key, s.model, s.timeout, s.max_retries) == (
        "https://x.test/v1", "k", "m", 7.0, 1,
    )  # fmt: skip
    assert s.enabled


async def test_cut_off_reply_is_an_error_and_extra_body_is_sent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "Blood oxygen is"},
                        "finish_reason": "length",
                    }
                ]
            },
        )

    p = make(handler, extra_body={"some_switch": {"type": "off"}}, max_tokens=50)
    with pytest.raises(LLMError, match="cut off"):
        await p.chat(MESSAGES)
    assert seen["body"]["some_switch"] == {"type": "off"}
    assert seen["body"]["max_tokens"] == 50


def test_extra_body_is_read_as_json_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"a": {"b": 1}}')
    assert LLMSettings(_env_file=None).extra_body == {"a": {"b": 1}}


async def test_hourly_cap_refuses_extra_requests_and_usage_is_counted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        })  # fmt: skip

    p = make(handler, max_calls_per_hour=2)
    assert await p.chat(MESSAGES) == "ok"
    assert await p.chat(MESSAGES) == "ok"
    with pytest.raises(LLMError, match="cap"):
        await p.chat(MESSAGES)
    assert p.usage() == {"requests": 2, "refused_by_cap": 1,
                         "prompt_tokens": 200, "completion_tokens": 40}  # fmt: skip

    unlimited = make(handler, max_calls_per_hour=0)
    for _ in range(5):
        await unlimited.chat(MESSAGES)
    assert unlimited.usage()["requests"] == 5
