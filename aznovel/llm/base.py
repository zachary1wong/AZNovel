"""LLM Provider protocol and shared types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    content: str
    model: str
    usage: TokenUsage | None = None
    raw: dict | None = None


@dataclass
class TokenUsage:
    """Token usage statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMConfig:
    """Configuration for an LLM provider."""

    provider: str = "openai"  # "openai" or "anthropic"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 300.0
    max_retries: int = 3


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that all LLM providers must implement."""

    config: LLMConfig

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request and return plain text."""
        ...

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict:
        """Send a chat request expecting JSON output. Parses and returns dict."""
        ...

    async def close(self) -> None:
        """Clean up resources."""
        ...
