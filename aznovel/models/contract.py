"""Contract models - the source of truth for writing constraints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MasterSetting(BaseModel):
    """Global story contract. Source of truth for tone, constraints, and genre."""

    contract_type: str = "MASTER_SETTING"
    genre: str = ""
    sub_genres: list[str] = Field(default_factory=list)
    core_tone: str = ""  # 核心调性
    pacing_strategy: str = ""  # 节奏策略
    satisfaction_points: list[str] = Field(default_factory=list)  # 爽点设计
    anti_patterns: list[str] = Field(default_factory=list)  # 反模式/毒点
    style_priorities: list[str] = Field(default_factory=list)  # 风格优先级
    world_rules: list[str] = Field(default_factory=list)  # 世界观规则
    golden_finger: str = ""  # 金手指描述
    protagonist_archetype: str = ""  # 主角原型
    constraints: list[str] = Field(default_factory=list)  # 创作约束


class ChapterBrief(BaseModel):
    """Per-chapter writing contract."""

    contract_type: str = "CHAPTER_BRIEF"
    chapter_number: int = 0
    title: str = ""
    summary: str = ""  # 大纲中的剧情摘要，必须遵循
    goal: str = ""
    resistance: str = ""
    cost: str = ""
    key_nodes: list[str] = Field(default_factory=list)
    character_states: dict[str, str] = Field(default_factory=dict)
    time_anchor: str = ""
    ending_target: str = ""
    forbidden_zones: list[str] = Field(default_factory=list)
    must_cover: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)


class ReviewContract(BaseModel):
    """Contract defining what the reviewer should check."""

    contract_type: str = "REVIEW_CONTRACT"
    chapter_number: int = 0
    check_settings: bool = True
    check_timeline: bool = True
    check_continuity: bool = True
    check_character: bool = True
    check_logic: bool = True
    check_ai_flavor: bool = True
    check_outline_compliance: bool = True
    known_entities: list[str] = Field(default_factory=list)
    established_rules: list[str] = Field(default_factory=list)
    previous_chapter_summary: str = ""
    blocking_keywords: list[str] = Field(default_factory=list)
    must_cover: list[str] = Field(default_factory=list)
    outline_summary: str = ""
