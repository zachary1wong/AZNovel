"""Anthropic Claude LLM provider."""

from __future__ import annotations

import json
import logging

import anthropic

from aznovel.llm.base import LLMConfig, LLMResponse, TokenUsage

logger = logging.getLogger(__name__)

_JSON_INSTRUCTION = (
    "\n\nYou MUST respond with valid JSON only. No markdown, no explanation, "
    "just the JSON object."
)


class AnthropicProvider:
    """Anthropic Claude chat completion provider."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        kwargs: dict = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self._client = anthropic.AsyncAnthropic(**kwargs)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        # Anthropic requires system message separate from messages
        system_text, chat_messages = self._extract_system(messages)

        resp = await self._client.messages.create(
            model=self.config.model,
            system=system_text,
            messages=chat_messages,
            temperature=temperature if temperature is not None else self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens,
            timeout=self.config.timeout,
        )
        # Extract text from content blocks (skip tool_use or other non-text blocks)
        content = ""
        if resp.content:
            for block in resp.content:
                if hasattr(block, "text"):
                    content = block.text
                    break
        usage = TokenUsage(
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
            total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
        )
        return LLMResponse(
            content=content,
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

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Parse JSON from LLM response, handling code fences and common issues."""
        import re
        # Strip code fences
        if "```" in text:
            # Remove ```json ... ``` or ``` ... ```
            match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()
        # Try parsing
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise

    @staticmethod
    def _extract_system(
        messages: list[dict[str, str]],
    ) -> tuple[str, list[dict[str, str]]]:
        """Extract system message from messages list (Anthropic uses separate param)."""
        system_parts: list[str] = []
        chat_messages: list[dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                chat_messages.append(msg)
        return "\n\n".join(system_parts), chat_messages
