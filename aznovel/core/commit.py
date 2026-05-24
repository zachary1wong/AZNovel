"""Chapter commit - extract facts and project to state."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from aznovel.llm.base import LLMProvider
from aznovel.models.chapter import ChapterCommit
from aznovel.models.project import ProjectState
from aznovel.models.review import ReviewResult
from aznovel.storage import project_fs
from aznovel.storage.state_store import StateStore
from aznovel.utils.text import count_chinese_chars

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM_PROMPT = """你是一个小说数据提取专家。从章节文本中提取结构化事实。

输出格式（严格JSON）：
{
  "summary": "200字以内的章节摘要",
  "events": [
    {"type": "事件类型", "description": "事件描述", "characters": ["相关人物"]}
  ],
  "state_deltas": {
    "protagonist": {"field": "新值"},
    "world": {"field": "新值"}
  },
  "entity_deltas": [
    {"name": "实体名", "type": "character/location/item", "changes": {"field": "新值"}}
  ],
  "new_entities": [
    {"name": "新实体名", "type": "character/location/item/organization", "description": "描述"}
  ]
}

只提取明确出现在文本中的信息。不要推测或添加文本中没有的内容。"""


class CommitService:
    """Handles chapter commits: fact extraction + state projection."""

    def __init__(self, provider: LLMProvider, root: Path) -> None:
        self._provider = provider
        self.root = root
        self._paths = project_fs.project_paths(root)
        self._state_store = StateStore(root)

    async def commit_chapter(
        self,
        chapter_number: int,
        chapter_text: str,
        chapter_title: str,
        review_result: ReviewResult,
    ) -> ChapterCommit:
        """Full commit pipeline: extract → validate → persist → project."""
        # Step 1: Extract facts from chapter
        extraction = await self._extract_facts(chapter_text)

        # Step 2: Build commit record
        commit = ChapterCommit(
            chapter_number=chapter_number,
            title=chapter_title,
            status="accepted" if review_result.passed else "rejected",
            summary=extraction.get("summary", ""),
            state_deltas=extraction.get("state_deltas", {}),
            entity_deltas=extraction.get("entity_deltas", []),
            new_entities=extraction.get("new_entities", []),
            events=extraction.get("events", []),
            review_issues=[
                i.model_dump() for i in review_result.issues
            ],
        )

        # Step 3: Persist commit
        self._save_commit(commit)

        # Step 4: Project to state (if accepted)
        if commit.status == "accepted":
            word_count = count_chinese_chars(chapter_text)
            self._project_to_state(commit, word_count)

        return commit

    async def _extract_facts(self, chapter_text: str) -> dict:
        """Use LLM to extract structured facts from chapter text."""
        messages = [
            {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": f"请从以下章节中提取结构化事实：\n\n{chapter_text}"},
        ]
        try:
            return await self._provider.chat_json(messages, temperature=0.0)
        except Exception as e:
            logger.warning(f"Fact extraction failed, using defaults: {e}")
            return {
                "summary": chapter_text[:200] + "..." if len(chapter_text) > 200 else chapter_text,
                "events": [],
                "state_deltas": {},
                "entity_deltas": [],
                "new_entities": [],
            }

    def _save_commit(self, commit: ChapterCommit) -> None:
        """Persist commit record to disk."""
        path = self._paths["commits_dir"] / f"chapter_{commit.chapter_number:03d}.commit.json"
        project_fs.save_json(path, commit.model_dump())
        logger.info(f"Commit saved: {path}")

    def _project_to_state(self, commit: ChapterCommit, word_count: int = 0) -> None:
        """Project commit deltas into state.json."""
        def apply_deltas(state: ProjectState) -> None:
            # Update protagonist state
            prot_delta = commit.state_deltas.get("protagonist", {})
            for key, val in prot_delta.items():
                if hasattr(state.protagonist, key):
                    setattr(state.protagonist, key, val)

            # Update progress
            state.progress.current_chapter = max(
                state.progress.current_chapter, commit.chapter_number
            )
            state.progress.total_words += word_count

            # Add new entities
            for ent in commit.new_entities:
                from aznovel.models.project import EntityRecord
                state.entities.append(EntityRecord(
                    id=ent.get("name", "").lower().replace(" ", "_"),
                    name=ent.get("name", ""),
                    type=ent.get("type", "character"),
                    first_appearance=commit.chapter_number,
                    state={"description": ent.get("description", "")},
                ))

        self._state_store.update(apply_deltas)
        logger.info(f"State projected for chapter {commit.chapter_number}")
