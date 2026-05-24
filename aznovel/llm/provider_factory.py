"""Factory for creating LLM providers."""

from __future__ import annotations

from aznovel.llm.base import LLMConfig, LLMProvider


def create_provider(config: LLMConfig) -> LLMProvider:
    """Create an LLM provider based on config.provider."""
    if config.provider == "anthropic":
        from aznovel.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config)
    else:
        from aznovel.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(config)
