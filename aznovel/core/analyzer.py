"""Analyzer - extracts structure from existing novel text."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from aznovel.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_ANALYZE_PROMPT = """你是一个小说分析专家。分析以下已写好的小说内容，提取结构化信息。

输出JSON：
{{
  "title": "小说标题（如果能推断出）",
  "genre": "题材类型",
  "writing_style": "写作风格描述（2-3句话）",
  "protagonist": {{
    "name": "主角名",
    "identity": "身份/背景",
    "personality": "性格特点",
    "current_goal": "当前目标",
    "special_abilities": ["能力"]
  }},
  "characters": [
    {{"name": "角色名", "identity": "身份", "relationship": "与主角关系", "status": "当前状态"}}
  ],
  "locations": ["重要地点"],
  "plot_threads": [
    {{"name": "线索名", "status": "active/resolved/dormant", "summary": "简述"}}
  ],
  "current_situation": "当前剧情进展到哪里（3-5句话）",
  "unresolved_mysteries": ["未解之谜"],
  "foreshadowing": ["已埋伏笔"],
  "chapters_count": 已有章节数,
  "chapter_summaries": [
    {{"chapter": 1, "summary": "一句话摘要"}}
  ]
}}"""

_ANALYZE_SETTINGS_PROMPT = """你是一个小说设定分析专家。从以下设定文本中提取结构化信息。

输出JSON：
{{
  "title": "小说标题",
  "genre": "题材",
  "world_setting": "世界观概述",
  "power_system": "力量体系（如有）",
  "protagonist": {{
    "name": "主角名",
    "identity": "身份",
    "personality": "性格",
    "goal": "目标",
    "special_abilities": ["能力"]
  }},
  "characters": [
    {{"name": "名字", "identity": "身份", "relationship": "与主角关系"}}
  ],
  "key_rules": ["重要规则/设定"],
  "conflict": "核心冲突"
}}"""


async def analyze_novel_text(provider: LLMProvider, text: str) -> dict:
    """Analyze existing novel text and extract structure."""
    # Truncate if too long (keep first ~15000 chars for analysis)
    if len(text) > 15000:
        text = text[:15000] + "\n\n[... 后续内容已省略 ...]"

    messages = [
        {"role": "system", "content": _ANALYZE_PROMPT},
        {"role": "user", "content": f"请分析以下小说内容：\n\n{text}"},
    ]
    try:
        return await provider.chat_json(messages, temperature=0.0)
    except Exception as e:
        logger.error(f"Novel analysis failed: {e}")
        return {"error": str(e)}


async def analyze_settings_text(provider: LLMProvider, text: str) -> dict:
    """Analyze setting text and extract structure."""
    messages = [
        {"role": "system", "content": _ANALYZE_SETTINGS_PROMPT},
        {"role": "user", "content": f"请分析以下设定文本：\n\n{text}"},
    ]
    try:
        return await provider.chat_json(messages, temperature=0.0)
    except Exception as e:
        logger.error(f"Settings analysis failed: {e}")
        return {"error": str(e)}


async def generate_outline(
    provider: LLMProvider,
    title: str,
    genre: str,
    protagonist: dict,
    world_setting: str = "",
    existing_summary: str = "",
    target_chapters: int = 600,
    chapters_per_volume: int = 50,
) -> dict:
    """Generate a novel outline."""
    volumes = target_chapters // chapters_per_volume

    prompt = f"""你是一个专业的小说大纲策划师。请为以下小说生成详细大纲。

## 小说信息
- 标题：{title}
- 题材：{genre}
- 目标章数：{target_chapters}章（{volumes}卷，每卷{chapters_per_volume}章）

## 主角
{json.dumps(protagonist, ensure_ascii=False, indent=2)}

## 世界观
{world_setting or '待设计'}

## 已有剧情（如有）
{existing_summary or '从头开始'}

请生成大纲，输出JSON：
{{
  "master_outline": "总纲概述（3-5句话描述整个故事走向）",
  "volumes": [
    {{
      "volume": 1,
      "title": "卷标题",
      "summary": "本卷概述（3-5句话）",
      "key_conflicts": ["核心冲突"],
      "climax": "本卷高潮",
      "chapter_range": "第1-50章",
      "chapters": [
        {{
          "chapter": 1,
          "title": "章节标题",
          "goal": "本章目标",
          "summary": "一句话剧情"
        }}
      ]
    }}
  ]
}}

注意：
- 第一卷只需要详细到每章的概述
- 后续卷只需要卷级别的概述
- 大纲要有起伏节奏，不能匀速推进
- 每卷要有明确的高潮点"""

    messages = [
        {"role": "system", "content": "你是一个专业的小说大纲策划师。"},
        {"role": "user", "content": prompt},
    ]
    return await provider.chat_json(messages, temperature=0.7, max_tokens=8192)


async def revise_outline(
    provider: LLMProvider,
    current_outline: dict,
    user_feedback: str,
) -> dict:
    """Revise outline based on user feedback."""
    prompt = f"""你是一个专业的小说大纲策划师。用户对当前大纲有修改意见，请根据反馈调整大纲。

## 当前大纲
{json.dumps(current_outline, ensure_ascii=False, indent=2)}

## 用户反馈
{user_feedback}

请根据反馈修改大纲，输出完整的修改后大纲JSON（格式与原大纲相同）。
只修改用户提到的部分，其他保持不变。"""

    messages = [
        {"role": "system", "content": "你是一个专业的小说大纲策划师。"},
        {"role": "user", "content": prompt},
    ]
    return await provider.chat_json(messages, temperature=0.5, max_tokens=8192)
