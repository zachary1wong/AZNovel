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
    requirements: str = "",
    chapter_1_content: str = "",
) -> dict:
    """Generate a novel outline."""
    volumes = target_chapters // chapters_per_volume

    # Build prompt - put requirements FIRST if present (highest priority)
    prompt = ""

    if requirements:
        prompt += f"""# 创作需求（最高优先级，必须严格遵循）

{requirements}

---
"""

    prompt += f"""# 小说基本信息
- 标题：{title}
- 题材：{genre}
- 目标章数：{target_chapters}章（{volumes}卷，每卷{chapters_per_volume}章）

## 主角
{json.dumps(protagonist, ensure_ascii=False, indent=2)}

## 世界观
{world_setting or '待设计'}
"""

    if existing_summary:
        prompt += f"""
## 已有剧情
{existing_summary}
"""

    if chapter_1_content:
        # Truncate if too long but keep enough for context
        if len(chapter_1_content) > 6000:
            chapter_1_content = chapter_1_content[:6000] + "\n...（后续省略）"
        prompt += f"""
## 已完成的第一章内容（必须保留，不可修改）
以下是已经写好的第一章全文。大纲中第1章的标题和摘要必须与实际内容一致。

{chapter_1_content}
"""

    prompt += f"""
# 输出要求

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
      "chapter_range": "第1-{chapters_per_volume}章",
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

# 硬性规则（违反任何一条都是不合格的输出）
1. **每一卷都必须有完整的逐章明细**，每章都需要列出 chapter、title、goal、summary
2. 大纲要有起伏节奏，不能匀速推进，每卷要有明确的高潮点
3. 如果提供了「创作需求」，必须**逐条对照**需求中的角色设定、出场顺序、剧情走向、结局要求，不允许自行发挥偏离
4. 如果提供了「已完成的第一章内容」，第1章的大纲必须与实际内容完全一致，不得重写或虚构
5. 从第2章开始规划后续剧情，第2章必须自然承接第1章的结尾"""

    messages = [
        {"role": "system", "content": "你是一个专业的小说大纲策划师。你的唯一任务是严格按照用户提供的创作需求来设计大纲，不允许自行发挥、添加用户未要求的元素、或忽略用户的具体设定。"},
        {"role": "user", "content": prompt},
    ]
    return await provider.chat_json(messages, temperature=0.3, max_tokens=16384)


async def revise_outline(
    provider: LLMProvider,
    current_outline: dict,
    user_feedback: str,
) -> dict:
    """Revise outline based on user feedback."""
    # Determine if this is detailed requirements or minor feedback
    is_detailed = len(user_feedback) > 500

    if is_detailed:
        prompt = f"""你是一个专业的小说大纲策划师。用户提供了详细的创作需求，请根据需求重新设计大纲。

## 当前大纲（仅供参考，可以大幅修改）
{json.dumps(current_outline, ensure_ascii=False, indent=2)}

## 用户的创作需求（必须严格遵循）
{user_feedback}

请根据用户需求重新生成大纲，输出完整的修改后大纲JSON（格式与原大纲相同）。
**必须严格按照用户需求来设计，包括角色设定、出场顺序、剧情走向、结局等。不要自行发挥偏离需求。**"""
    else:
        prompt = f"""你是一个专业的小说大纲策划师。用户对当前大纲有修改意见，请根据反馈调整大纲。

## 当前大纲
{json.dumps(current_outline, ensure_ascii=False, indent=2)}

## 用户反馈
{user_feedback}

请根据反馈修改大纲，输出完整的修改后大纲JSON（格式与原大纲相同）。
只修改用户提到的部分，其他保持不变。"""

    messages = [
        {"role": "system", "content": "你是一个专业的小说大纲策划师。你必须严格按照用户提供的需求来设计大纲。"},
        {"role": "user", "content": prompt},
    ]
    return await provider.chat_json(messages, temperature=0.5, max_tokens=16384)


def _summarize_chapter(content: str, max_head: int = 500, max_tail: int = 200) -> str:
    """Extract a summary from chapter content: first N chars + last N chars."""
    if len(content) <= max_head + max_tail:
        return content
    return content[:max_head] + "\n...\n" + content[-max_tail:]


async def reverse_outline(
    provider: LLMProvider,
    chapters: list[dict],
    title: str = "",
    genre: str = "",
) -> dict:
    """Generate an outline by analyzing already-written chapters.

    Args:
        chapters: [{"number": 1, "title": "...", "content": "..."}]
    Returns:
        Outline dict in the same format as generate_outline.
    """
    if not chapters:
        return {"error": "没有章节内容"}

    # Step 1: Summarize each chapter
    summaries = []
    for ch in chapters:
        summary = _summarize_chapter(ch["content"])
        summaries.append({
            "chapter": ch["number"],
            "title": ch.get("title", f"第{ch['number']}章"),
            "summary": summary,
        })

    # Step 2: Group into volumes (10 chapters per volume)
    chapters_per_volume = 10
    volumes: list[list[dict]] = []
    for i in range(0, len(summaries), chapters_per_volume):
        volumes.append(summaries[i:i + chapters_per_volume])

    # Step 3: Generate chapter details for each volume
    volume_results = []
    for vol_idx, vol_chapters in enumerate(volumes):
        vol_num = vol_idx + 1
        chapters_text = "\n\n".join(
            f"### 第{c['chapter']}章: {c['title']}\n{c['summary']}"
            for c in vol_chapters
        )

        prompt = f"""你是一个小说分析专家。分析以下第{vol_num}卷的章节内容，提取章节明细。

## 小说信息
- 标题：{title or '未知'}
- 题材：{genre or '未知'}

## 第{vol_num}卷章节内容
{chapters_text}

输出JSON（只需本卷的章节明细）：
{{
  "volume": {vol_num},
  "title": "卷标题（根据内容推断）",
  "summary": "本卷概述（3-5句话）",
  "key_conflicts": ["核心冲突"],
  "climax": "本卷高潮",
  "chapter_range": "第{vol_chapters[0]['chapter']}-{vol_chapters[-1]['chapter']}章",
  "chapters": [
    {{"chapter": {vol_chapters[0]['chapter']}, "title": "章节标题", "goal": "本章目标", "summary": "一句话剧情摘要"}}
  ]
}}

注意：必须包含本卷所有章节的明细。"""

        messages = [
            {"role": "system", "content": "你是一个小说分析专家，擅长从已有内容中提取结构。"},
            {"role": "user", "content": prompt},
        ]
        try:
            result = await provider.chat_json(messages, temperature=0.0, max_tokens=8192)
            volume_results.append(result)
        except Exception as e:
            logger.error(f"Volume {vol_num} analysis failed: {e}")
            volume_results.append({
                "volume": vol_num,
                "title": f"第{vol_num}卷",
                "summary": "分析失败",
                "chapters": [
                    {"chapter": c["chapter"], "title": c["title"], "goal": "", "summary": ""}
                    for c in vol_chapters
                ],
            })

    # Step 4: Generate master outline
    volume_summaries = "\n\n".join(
        f"第{v.get('volume', i+1)}卷《{v.get('title', '')}》：{v.get('summary', '')}"
        for i, v in enumerate(volume_results)
    )

    master_prompt = f"""你是一个小说分析专家。根据以下各卷概述，生成总纲。

## 小说信息
- 标题：{title or '未知'}
- 题材：{genre or '未知'}
- 总章数：{len(chapters)}

## 各卷概述
{volume_summaries}

输出JSON：
{{
  "master_outline": "总纲概述（3-5句话描述整个故事走向和主题）"
}}"""

    messages = [
        {"role": "system", "content": "你是一个小说分析专家。"},
        {"role": "user", "content": master_prompt},
    ]
    try:
        master = await provider.chat_json(messages, temperature=0.0, max_tokens=2048)
    except Exception as e:
        logger.error(f"Master outline generation failed: {e}")
        master = {"master_outline": "总纲生成失败"}

    # Step 5: Assemble final outline
    return {
        "master_outline": master.get("master_outline", ""),
        "volumes": volume_results,
    }
