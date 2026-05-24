"""OpenAI-compatible LLM provider (works with GPT, DeepSeek, Qwen, local models, etc.)."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from aznovel.llm.base import LLMConfig, LLMResponse, TokenUsage

logger = logging.getLogger(__name__)

# JSON mode instruction appended to system message
_JSON_INSTRUCTION = (
    "\n\nYou MUST respond with valid JSON only. No markdown, no explanation, "
    "just the JSON object."
)


class OpenAIProvider:
    """OpenAI-compatible chat completion provider."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        kwargs: dict[str, Any] = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self._client = AsyncOpenAI(**kwargs)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        resp = await self._client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens,
            timeout=self.config.timeout,
        )
        choice = resp.choices[0]
        usage = None
        if resp.usage:
            usage = TokenUsage(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                total_tokens=resp.usage.total_tokens,
            )
        return LLMResponse(
            content=choice.message.content or "",
            model=resp.model,
            usage=usage,
        )

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict:
        # Inject JSON instruction into the last user message
        modified = list(messages)
        if modified and modified[-1]["role"] == "user":
            modified[-1] = {
                "role": "user",
                "content": modified[-1]["content"] + _JSON_INSTRUCTION,
            }
        else:
            modified.append({"role": "user", "content": "Respond with valid JSON only."})

        resp = await self.chat(modified, temperature=temperature, max_tokens=max_tokens)
        text = resp.content.strip()
        return self._parse_json(text)

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Parse JSON from LLM response, handling code fences and common issues."""
        import re
        if "```" in text:
            match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise

    async def close(self) -> None:
        await self._client.close()
