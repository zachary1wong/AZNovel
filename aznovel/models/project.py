"""Project-level data models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectInfo(BaseModel):
    """Basic project metadata."""

    title: str = ""
    genre: str = ""
    author: str = ""
    target_chapters: int = 600
    chapters_per_volume: int = 50
    created_at: str = ""


class ProtagonistState(BaseModel):
    """Current state of the protagonist."""

    name: str = ""
    age: int = 0
    cultivation: str = ""  # 修为/等级
    location: str = ""
    mood: str = ""
    current_goal: str = ""
    special_abilities: list[str] = Field(default_factory=list)


class PlotThread(BaseModel):
    """An active plot thread."""

    id: str = ""
    name: str = ""
    status: str = "active"  # active, resolved, dormant
    introduced_chapter: int = 0
    summary: str = ""


class ProjectState(BaseModel):
    """Full project state, persisted to .aznovel/state.json."""

    version: str = "1.0"
    project_info: ProjectInfo = Field(default_factory=ProjectInfo)
    progress: ProgressInfo = Field(default_factory=lambda: ProgressInfo())
    protagonist: ProtagonistState = Field(default_factory=ProtagonistState)
    plot_threads: list[PlotThread] = Field(default_factory=list)
    entities: list[EntityRecord] = Field(default_factory=list)


class ProgressInfo(BaseModel):
    """Writing progress tracking."""

    current_chapter: int = 0
    total_chapters: int = 0
    current_volume: int = 1
    total_words: int = 0


class EntityRecord(BaseModel):
    """A tracked entity (character, location, item, etc.)."""

    id: str = ""
    name: str = ""
    type: str = "character"  # character, location, item, organization
    aliases: list[str] = Field(default_factory=list)
    first_appearance: int = 0
    state: dict = Field(default_factory=dict)
