"""Chapter data models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChapterOutline(BaseModel):
    """Outline for a single chapter."""

    chapter_number: int
    title: str = ""
    goal: str = ""  # 本章目标
    resistance: str = ""  # 阻力/冲突
    cost: str = ""  # 代价
    key_nodes: list[str] = Field(default_factory=list)  # 关键剧情节点
    ending_feeling: str = ""  # 结尾感受
    forbidden_zones: list[str] = Field(default_factory=list)  # 禁忌区域
    time_anchor: str = ""  # 时间锚点


class ChapterContent(BaseModel):
    """A completed chapter."""

    chapter_number: int
    title: str
    content: str
    word_count: int = 0
    summary: str = ""


class ChapterCommit(BaseModel):
    """Commit record for a chapter (event-sourced)."""

    chapter_number: int
    title: str
    status: str = "accepted"  # accepted, rejected
    summary: str = ""
    state_deltas: dict = Field(default_factory=dict)
    entity_deltas: list[dict] = Field(default_factory=list)
    new_entities: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    review_issues: list[dict] = Field(default_factory=list)
