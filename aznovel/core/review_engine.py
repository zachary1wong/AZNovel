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
            result = ReviewResult(
                chapter_number=contract.chapter_number,
                summary=f"审查失败: {e}",
                issues=[
                    ReviewIssue(
                        severity="critical",
                        category="review_engine",
                        location="审查输出",
                        description=f"审查过程失败，无法确认章节质量: {e}",
                        evidence="",
                        fix_hint="请重新审查；若反复出现，请检查模型JSON输出是否完整有效。",
                        blocking=True,
                    )
                ],
            )
            result.compute_derived()
            return result

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
        issues = self._filter_unreliable_issues(issues, chapter_text, contract)

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

    def _filter_unreliable_issues(
        self,
        issues: list[ReviewIssue],
        chapter_text: str,
        contract: ReviewContract,
    ) -> list[ReviewIssue]:
        """Drop deterministic false positives from otherwise model-based reviews."""
        filtered: list[ReviewIssue] = []
        for issue in issues:
            if self._is_self_contradictory_outline_issue(issue, chapter_text, contract):
                logger.info(
                    "Filtered unreliable review issue for chapter %s: %s",
                    contract.chapter_number,
                    issue.description,
                )
                continue
            filtered.append(issue)
        return filtered

    def _is_self_contradictory_outline_issue(
        self,
        issue: ReviewIssue,
        chapter_text: str,
        contract: ReviewContract,
    ) -> bool:
        """Identify obvious hallucinated outline issues before they block repair."""
        text = "\n".join(
            part for part in [issue.description, issue.evidence, issue.fix_hint] if part
        )
        category_text = f"{issue.category}\n{text}"
        if not re.search(r"(outline|setting|character|entity|大纲|设定|人物|角色|实体)", category_text):
            return False
        if not text:
            return False

        established_facts = "\n".join(
            contract.established_rules + contract.must_cover + [contract.outline_summary]
        )
        protagonist = _protagonist_from_facts(established_facts)
        if protagonist and protagonist in chapter_text and protagonist in text:
            if re.search(r"(主角|配送员|人物名称|角色名|实体列表)", text) and re.search(
                r"(不符|矛盾|错位|偏离)", text
            ):
                return True

        quoted = re.findall(r"[“\"'‘]([^”\"'’]{1,30})[”\"'’]", text)
        if len(quoted) >= 2 and _normalized_name(quoted[0]) == _normalized_name(quoted[1]):
            if re.search(r"(写为|写成|误写|改成|替换|名称|名字|角色名)", text):
                return True

        known_entities = [name for name in contract.known_entities if name]
        for entity in known_entities:
            if entity not in chapter_text or entity not in text:
                continue
            if _facts_define_as_child(established_facts, entity) and re.search(
                rf"{re.escape(entity)}.*(应为|应该是).{{0,12}}(主角|配送员)|"
                rf"(而非|不是|不应为).{{0,8}}儿子",
                text,
            ):
                return True
            if self._claims_entity_absent_from_whole_chapter(text, entity):
                return True

        return False

    def _claims_entity_absent_from_whole_chapter(self, text: str, entity: str) -> bool:
        clauses = re.split(r"[。；;！!\n]", text)
        absence = r"(未出现|没有出现|未提及|没有提及|缺失|缺少|全篇未见|全文未见|文中未见|全章未见)"
        whole_scope = r"(正文|全文|全篇|文中|章节|全章)"
        entity_pat = re.escape(entity)
        for clause in clauses:
            if entity not in clause:
                continue
            if not re.search(absence, clause):
                continue
            if not re.search(whole_scope, clause):
                continue
            if re.search(rf"{absence}.{{0,16}}[“\"'‘]?{entity_pat}[”\"'’]?", clause):
                return True
            if re.search(rf"[“\"'‘]?{entity_pat}[”\"'’]?.{{0,16}}{absence}", clause):
                return True
        return False


def _normalized_name(name: str) -> str:
    return re.sub(r"\s+", "", name.strip())


def _protagonist_from_facts(facts: str) -> str:
    match = re.search(r"主角是([^\s，,。；;]+)", facts)
    return match.group(1).strip() if match else ""


def _facts_define_as_child(facts: str, entity: str) -> bool:
    entity_pat = re.escape(entity)
    return bool(
        re.search(rf"(儿子|孩子|子女).{{0,8}}{entity_pat}", facts)
        or re.search(rf"{entity_pat}.{{0,8}}(儿子|孩子|子女)", facts)
    )


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
