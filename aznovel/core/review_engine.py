"""Multi-dimensional review engine."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from aznovel.llm.base import LLMProvider
from aznovel.models.contract import ReviewContract
from aznovel.models.review import ReviewIssue, ReviewResult

logger = logging.getLogger(__name__)

_REVIEW_SYSTEM_PROMPT = """你是一个专业的小说审查编辑。请从以下7个维度检查章节问题：

1. 设定一致性：世界观、力量体系、人物设定是否矛盾
2. 时间线：事件时间顺序是否合理
3. 叙事连续性：与前文衔接、伏笔、重复描写
4. 人物一致性：角色行为是否符合性格设定（OOC）
5. 逻辑：因果关系、战斗结果是否可信
6. AI味：泛化副词、句式单一、情感直白命名、展示后叙述解释
7. 大纲合规性：正文是否严格遵循了本章大纲的要求，大纲中指定的角色、事件、场景是否全部出现

审查规则：
- 只报告可验证的问题，每个问题必须有文本证据
- 严重程度：critical/high/medium/low
- critical和high标记为blocking
- 不要提出修改建议，只指出问题
- 大纲合规性问题：如果大纲要求的内容（角色、事件、场景）在正文中缺失或偏离，必须标记为 critical 级别

输出JSON：
{{
  "issues": [
    {{"severity": "high", "category": "setting", "location": "第2段", "description": "...", "evidence": "原文", "fix_hint": "", "blocking": true}}
  ],
  "summary": "一句话总结"
}}"""


class ReviewEngine:
    """Multi-dimensional chapter review engine."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def review_chapter(
        self,
        chapter_text: str,
        contract: ReviewContract,
        *,
        dimensions: list[str] | None = None,
    ) -> ReviewResult:
        """Run review on a chapter (all dimensions in one LLM call)."""
        prompt = self._build_prompt(chapter_text, contract)

        messages = [
            {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            raw = await self._provider.chat_json(messages, temperature=0.0)
        except Exception as e:
            logger.error(f"Review failed: {e}")
            return ReviewResult(
                chapter_number=contract.chapter_number,
                summary=f"审查失败: {e}",
                passed=True,  # Don't block on review failure
            )

        issues = []
        for item in raw.get("issues", []):
            issues.append(ReviewIssue(
                severity=item.get("severity", "medium"),
                category=item.get("category", ""),
                location=item.get("location", ""),
                description=item.get("description", ""),
                evidence=item.get("evidence", ""),
                fix_hint=item.get("fix_hint", ""),
                blocking=item.get("blocking", False),
            ))

        result = ReviewResult(
            chapter_number=contract.chapter_number,
            issues=issues,
            summary=raw.get("summary", ""),
        )
        result.compute_derived()
        return result

    def _build_prompt(self, chapter_text: str, contract: ReviewContract) -> str:
        parts = []

        if contract.outline_summary:
            parts.append("## 本章大纲要求（必须严格遵循）")
            parts.append(contract.outline_summary)

        if contract.must_cover:
            parts.append("\n## 必须覆盖的内容")
            for item in contract.must_cover:
                parts.append(f"- {item}")

        if contract.established_rules:
            parts.append("\n## 已建立的规则")
            for rule in contract.established_rules:
                parts.append(f"- {rule}")

        if contract.known_entities:
            parts.append(f"\n## 已知实体\n{', '.join(contract.known_entities)}")

        if contract.previous_chapter_summary:
            parts.append(f"\n## 前章摘要\n{contract.previous_chapter_summary}")

        parts.append(f"\n## 待审查章节\n{chapter_text}")

        return "\n".join(parts)


def format_review_report(result: ReviewResult) -> str:
    """Format review result as markdown report."""
    lines = [f"# 审查报告 - 第{result.chapter_number}章\n"]

    status = "通过" if result.passed else "未通过"
    lines.append(f"**状态**: {status}")
    lines.append(f"**问题数**: {len(result.issues)} (阻断: {result.blocking_count})\n")

    if result.summary:
        lines.append(f"## 总结\n{result.summary}\n")

    if result.issues:
        lines.append("## 问题列表\n")
        for i, issue in enumerate(result.issues, 1):
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(issue.severity, "⚪")
            tag = " [BLOCKING]" if issue.blocking else ""
            lines.append(f"### {icon} 问题 {i}{tag}")
            lines.append(f"- **类别**: {issue.category}")
            lines.append(f"- **位置**: {issue.location}")
            lines.append(f"- **描述**: {issue.description}")
            if issue.evidence:
                lines.append(f"- **证据**: > {issue.evidence}")
            if issue.fix_hint:
                lines.append(f"- **修复**: {issue.fix_hint}")
            lines.append("")

    return "\n".join(lines)
