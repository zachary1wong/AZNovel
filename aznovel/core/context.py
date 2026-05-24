"""Context assembly - builds writing task briefs from contracts and state."""

from __future__ import annotations

from pathlib import Path

from aznovel.models.contract import ChapterBrief, MasterSetting
from aznovel.models.project import ProjectState
from aznovel.storage import project_fs
from aznovel.storage.template_loader import is_literary_genre


def _is_literary(state: ProjectState) -> bool:
    """Check if the project is literary fiction."""
    return is_literary_genre(state.project_info.genre)


def build_writing_brief(
    chapter_brief: ChapterBrief,
    master_setting: MasterSetting,
    state: ProjectState,
    previous_summary: str = "",
    previous_chapter_text: str = "",
) -> str:
    """Build a 5-section writing task brief (上下文组装).

    This is the core prompt that guides the LLM to write a chapter.
    """
    sections: list[str] = []

    # Section 1: Opening commission
    sections.append(_build_commission(chapter_brief, state))

    # Section 2: This chapter's story
    sections.append(_build_story_context(chapter_brief, master_setting, previous_summary))

    # Section 3: Characters
    sections.append(_build_character_section(chapter_brief, state))

    # Section 4: Writing guidance
    sections.append(_build_writing_guidance(master_setting, chapter_brief, state))

    # Section 5: Ending target
    sections.append(_build_ending_target(chapter_brief, state))

    return "\n\n---\n\n".join(sections)


def _build_commission(brief: ChapterBrief, state: ProjectState) -> str:
    """Section 1: Opening commission."""
    lines = [
        f"# 写作任务书",
        f"**小说**: {state.project_info.title}",
        f"**章节**: 第{brief.chapter_number:03d}章 - {brief.title}",
        f"**目标**: {brief.goal}" if brief.goal else "",
        f"**字数要求**: 2000-2500字",
    ]
    return "\n".join(l for l in lines if l)


def _build_story_context(
    brief: ChapterBrief, master: MasterSetting, prev_summary: str
) -> str:
    """Section 2: This chapter's story context."""
    lines = ["# 本章剧情"]

    if prev_summary:
        lines.append(f"\n**前情提要**:\n{prev_summary}")

    if brief.goal:
        lines.append(f"\n**本章目标**: {brief.goal}")
    if brief.resistance:
        lines.append(f"**阻力/冲突**: {brief.resistance}")
    if brief.cost:
        lines.append(f"**代价**: {brief.cost}")
    if brief.key_nodes:
        lines.append(f"\n**关键节点**:")
        for node in brief.key_nodes:
            lines.append(f"- {node}")
    if brief.time_anchor:
        lines.append(f"\n**时间锚点**: {brief.time_anchor}")

    return "\n".join(lines)


def _build_character_section(brief: ChapterBrief, state: ProjectState) -> str:
    """Section 3: Characters in this chapter."""
    lines = ["# 本章人物"]

    if state.protagonist.name:
        p = state.protagonist
        lines.append(f"\n**主角: {p.name}**")
        if p.cultivation:
            # For literary genres, use "身份" instead of "境界"
            label = "身份" if _is_literary(state) else "境界"
            lines.append(f"  {label}: {p.cultivation}")
        if p.current_goal:
            lines.append(f"  当前目标: {p.current_goal}")
        if p.mood:
            lines.append(f"  心情: {p.mood}")
        if p.special_abilities:
            lines.append(f"  能力: {', '.join(p.special_abilities)}")

    if brief.character_states:
        for name, state_desc in brief.character_states.items():
            if name != state.protagonist.name:
                lines.append(f"\n**{name}**: {state_desc}")

    return "\n".join(lines)


def _build_writing_guidance(master: MasterSetting, brief: ChapterBrief, state: ProjectState | None = None) -> str:
    """Section 4: How to write it better. Adapts for literary vs web novel genres."""
    is_lit = state and _is_literary(state)

    lines = ["# 写作指导"]

    if master.core_tone:
        lines.append(f"\n**核心调性**: {master.core_tone}")
    if master.pacing_strategy:
        lines.append(f"**节奏策略**: {master.pacing_strategy}")

    # Web novel specific: satisfaction points
    if not is_lit and master.satisfaction_points:
        lines.append("\n**爽点设计**:")
        for sp in master.satisfaction_points:
            lines.append(f"- {sp}")

    # Literary specific: writing style guidance
    if is_lit:
        lines.append("\n**文学性要求**:")
        lines.append("- 注重语言的质感和节奏，避免口水化表达")
        lines.append("- 人物塑造要有层次，避免非黑即白")
        lines.append("- 细节描写要服务于主题和人物，不要无意义铺陈")
        lines.append("- 叙事要有自己的声音和风格")
        lines.append("- 情感表达要克制，通过细节和行为传达")

    # Anti-AI rules (common)
    lines.append("\n**反AI写作规则**:")
    lines.append("- 不要用总结性语句收尾")
    lines.append("- 不要用泛化副词（轻轻地、缓缓地、默默地）")
    lines.append("- 情绪通过生理反应展现，不要直接命名情绪")
    lines.append("- 对话要有潜台词，不要直白表达")
    lines.append("- 节奏要有变化，不要匀速推进")
    lines.append("- 展示而非叙述（Show, don't tell）")
    if is_lit:
        lines.append("- 避免鸡汤式感悟和说教")
        lines.append("- 避免过度煽情和刻意的金句")

    if brief.anti_patterns:
        lines.append("\n**本文禁忌**:")
        for ap in brief.anti_patterns:
            lines.append(f"- {ap}")

    if brief.forbidden_zones:
        lines.append("\n**本章禁忌**:")
        for fz in brief.forbidden_zones:
            lines.append(f"- {fz}")

    return "\n".join(lines)


def _build_ending_target(brief: ChapterBrief, state: ProjectState | None = None) -> str:
    """Section 5: Where to end."""
    is_lit = state and _is_literary(state)

    lines = ["# 结尾要求"]
    if brief.ending_target:
        lines.append(f"\n**结尾感受**: {brief.ending_target}")
    elif is_lit:
        lines.append("\n结尾要有余韵，可以是开放式的，留给读者思考空间。不必刻意制造悬念。")
    else:
        lines.append("\n结尾要有悬念或情绪钩子，让读者想继续看下一章。")
    if brief.must_cover:
        lines.append("\n**必须覆盖的内容**:")
        for mc in brief.must_cover:
            lines.append(f"- {mc}")
    return "\n".join(lines)
