"""Review result models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewIssue(BaseModel):
    """A single issue found during review."""

    severity: str = "medium"  # low, medium, high, critical
    category: str = ""  # setting, timeline, continuity, character, logic, ai_flavor
    location: str = ""  # e.g. "第3段" or "对话部分"
    description: str = ""
    evidence: str = ""  # exact text quote or data comparison
    fix_hint: str = ""
    blocking: bool = False


class ReviewResult(BaseModel):
    """Complete review output."""

    chapter_number: int = 0
    issues: list[ReviewIssue] = Field(default_factory=list)
    blocking_count: int = 0
    summary: str = ""
    passed: bool = True

    def compute_derived(self) -> None:
        """Compute blocking_count and passed from issues."""
        self.blocking_count = sum(1 for i in self.issues if i.blocking)
        self.passed = self.blocking_count == 0
