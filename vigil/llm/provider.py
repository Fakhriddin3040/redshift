"""The LLM Provider abstraction and its one implementation.

Business logic depends only on `LLMProvider`. `OpenAICompatibleProvider` speaks
the chat-completions protocol that most hosted and self-hosted servers accept,
so the provider is chosen by LLM_BASE_URL, not by code.
"""

import asyncio
import logging
import time
from collections import deque
from typing import Protocol

import httpx

from vigil.llm.config import LLMSettings

log = logging.getLogger("vigil.llm")

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": "..."}
RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
BACKOFF_START_S, BACKOFF_MAX_S = 0.5, 8.0


class LLMError(Exception):
    """The provider could not give an answer (after retries, if any were allowed)."""


class LLMProvider(Protocol):
    async def chat(
        self, messages: list[Message], *, max_tokens: int | None = None
    ) -> str:
        """Return the assistant's reply to a list of chat messages.
        `max_tokens` replaces the configured token limit for this one request."""
        ...

    def usage(self) -> dict[str, int]:
        """Requests and tokens spent since start (what the provider reported)."""
        ...

    async def aclose(self) -> None: ...


class OpenAICompatibleProvider:
    """POST {base_url}/chat/completions with timeouts, retries and logging."""

    def __init__(
        self, settings: LLMSettings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        self._calls: deque[float] = deque()  # start times of recent requests
        self._usage = {"requests": 0, "refused_by_cap": 0, "prompt_tokens": 0,
                       "completion_tokens": 0}  # fmt: skip
        self._client = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/") + "/",
            headers=headers,
            timeout=settings.timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def usage(self) -> dict[str, int]:
        return dict(self._usage)

    def _within_cap(self) -> bool:
        cap = self.settings.max_calls_per_hour
        now = time.monotonic()
        while self._calls and now - self._calls[0] > 3600:
            self._calls.popleft()
        if cap > 0 and len(self._calls) >= cap:
            return False
        self._calls.append(now)
        return True

    async def chat(
        self, messages: list[Message], *, max_tokens: int | None = None
    ) -> str:
        s = self.settings
        if not self._within_cap():
            self._usage["refused_by_cap"] += 1
            log.warning("llm not asked: %d requests in the last hour (LLM_MAX_CALLS_PER_HOUR)",
                        s.max_calls_per_hour)  # fmt: skip
            raise LLMError("hourly request cap reached")
        payload = {
            "model": s.model,
            "messages": messages,
            "temperature": s.temperature,
            "max_tokens": max_tokens or s.max_tokens,
            **s.extra_body,
        }
        attempts = max(0, s.max_retries) + 1
        last = "no attempt made"
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            retry_after = None
            try:
                resp = await self._client.post("chat/completions", json=payload)
            except httpx.TimeoutException:
                last = f"timeout after {s.timeout:g} s"
            except httpx.HTTPError as exc:
                last = f"connection error: {type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200:
                    tokens = self._count(resp)
                    text = self._content(resp)
                    log.info(
                        "llm ok: %.2f s, attempt %d/%d, %d chars, tokens in/out %s/%s",
                        time.monotonic() - started, attempt, attempts, len(text), *tokens,
                    )  # fmt: skip
                    return text
                last = f"HTTP {resp.status_code}: {resp.text[:200]!r}"
                if resp.status_code not in RETRY_STATUS:
                    log.error("llm failed, not retried: %s", last)
                    raise LLMError(last)
                retry_after = _retry_after(resp)
            if attempt < attempts:
                delay = retry_after or min(
                    BACKOFF_MAX_S, BACKOFF_START_S * 2 ** (attempt - 1)
                )
                log.warning(
                    "llm attempt %d/%d failed (%s), retrying in %.1f s",
                    attempt, attempts, last, delay,
                )  # fmt: skip
                await asyncio.sleep(delay)
        log.error("llm failed after %d attempts: %s", attempts, last)
        raise LLMError(last)

    def _count(self, resp: httpx.Response) -> tuple[int | str, int | str]:
        """Add the provider's own token count to the running totals."""
        self._usage["requests"] += 1
        try:
            used = resp.json().get("usage") or {}
            tin, tout = int(used["prompt_tokens"]), int(used["completion_tokens"])
        except ValueError, KeyError, TypeError, AttributeError:
            return "?", "?"
        self._usage["prompt_tokens"] += tin
        self._usage["completion_tokens"] += tout
        return tin, tout

    @staticmethod
    def _content(resp: httpx.Response) -> str:
        try:
            choice = resp.json()["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, LookupError, TypeError) as exc:
            raise LLMError(f"unexpected response shape: {resp.text[:200]!r}") from exc
        if choice.get("finish_reason") == "length":
            # Cut off by the token limit: a half sentence must never be shown.
            raise LLMError("reply cut off by the token limit (raise LLM_MAX_TOKENS)")
        if not isinstance(content, str) or not content.strip():
            raise LLMError("empty reply")
        return content.strip()


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return min(BACKOFF_MAX_S, max(0.0, float(resp.headers["retry-after"])))
    except KeyError, ValueError:
        return None


def create_provider(settings: LLMSettings) -> LLMProvider | None:
    """The configured provider, or None when the LLM is switched off."""
    if not settings.enabled:
        log.info("llm: off (LLM_BASE_URL and LLM_MODEL are not both set)")
        return None
    log.info(
        "llm: on, base url %s, timeout %g s, retries %d",
        settings.base_url, settings.timeout, settings.max_retries,
    )  # fmt: skip
    return OpenAICompatibleProvider(settings)
