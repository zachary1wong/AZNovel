"""Writing pipeline - orchestrates the 6-step chapter writing flow."""

from __future__ import annotations

import logging
from pathlib import Path

from aznovel.core.commit import CommitService
from aznovel.core.context import build_writing_brief
from aznovel.core.contract_manager import ContractManager
from aznovel.core.review_engine import ReviewEngine, format_review_report
from aznovel.llm.base import LLMProvider
from aznovel.models.contract import ChapterBrief, MasterSetting, ReviewContract
from aznovel.models.project import ProjectState
from aznovel.models.review import ReviewResult
from aznovel.storage import project_fs
from aznovel.storage.state_store import StateStore
from aznovel.storage.template_loader import load_genre, resolve_genre_alias
from aznovel.utils.rich_ui import console, error, info, panel, success, warn
from aznovel.utils.text import chapter_filename, count_chinese_chars, extract_chapter_number

logger = logging.getLogger(__name__)

_DRAFT_SYSTEM_PROMPT = """你是一个专业的中文{writer_type}。你的任务是根据写作任务书写一章小说。

写作规则：
1. 严格按照写作任务书的要求写作
2. 字数控制在{word_min}-{word_max}字
3. 不要写章节标题（标题会单独处理）
4. 直接输出正文内容
5. 不要用总结性语句收尾
6. 不要用泛化副词（轻轻地、缓缓地、默默地）
7. 情绪通过生理反应展现，不要直接命名情绪
8. 对话要有潜台词，不要直白表达
9. 节奏要有变化，不要匀速推进
10. 展示而非叙述（Show, don't tell）
{extra_rules}"""

_DRAFT_SYSTEM_PROMPT_DRAMA = """你是一个专业的短剧编剧。你的任务是根据写作任务书写一集短剧剧本。

写作规则：
1. 严格按照写作任务书的要求写作
2. 字数控制在{word_min}-{word_max}字
3. 不要写集数标题（标题会单独处理）
4. 直接输出剧本内容
5. 剧本格式：
   - 场景描述用【场景】标注
   - 角色动作用括号（）标注
   - 对话格式：角色名：台词内容
   - 旁白/画外音用「旁白」标注
6. 每集结尾必须有悬念钩子
7. 对话要短句为主，情绪张力强
8. 节奏要快，不要拖沓
9. 反转要合理但出人意料
10. 冲突要激烈，情绪要浓烈
{extra_rules}"""

_DRAFT_EXTRA_LITERARY = """11. 注重语言的质感和文学性
12. 人物塑造要有深度和层次
13. 细节描写要服务于主题
14. 避免鸡汤式感悟和刻意煽情"""

_DRAFT_EXTRA_WEBNOVEL = """11. 注意爽点节奏，读者体验优先
12. 适当设置悬念钩子"""

_DRAFT_EXTRA_DRAMA = """11. 强反转、快节奏、情绪冲击
12. 每集结尾必须有悬念
13. 对话要有潜台词和冲突
14. 场景转换要快，不要拖"""

_POLISH_SYSTEM_PROMPT = """你是一个专业的小说润色编辑。根据审查报告修复章节中的问题。

规则：
1. 只修复报告中指出的问题，不要大幅改动
2. 保持原文风格和节奏
3. 修复后字数保持在{word_min}-{word_max}字
4. 输出完整的润色后章节内容（不要输出标题）
5. 不要引入新的AI味"""

_POLISH_SYSTEM_PROMPT_DRAMA = """你是一个专业的短剧剧本润色编辑。根据审查报告修复剧本中的问题。

规则：
1. 只修复报告中指出的问题，不要大幅改动
2. 保持原文风格和节奏
3. 修复后字数保持在{word_min}-{word_max}字
4. 输出完整的润色后剧本内容（不要输出集数标题）
5. 保持剧本格式：【场景】、（动作）、角色名：台词、「旁白」
6. 不要引入新的AI味"""

_REWRITE_SYSTEM_PROMPT = """你是一个专业的小说编辑。用户想修改一个已有章节，请根据修改要求重写该章节。

规则：
1. 严格按照用户的修改要求重写
2. 保持与整体故事的连贯性
3. 字数控制在{word_min}-{word_max}字
4. 不要写章节标题
5. 保持原文的写作风格（除非用户要求改变风格）
6. 直接输出重写后的正文内容"""

_REWRITE_SYSTEM_PROMPT_DRAMA = """你是一个专业的短剧编剧。用户想修改一集剧本，请根据修改要求重写。

规则：
1. 严格按照用户的修改要求重写
2. 保持与整体故事的连贯性
3. 字数控制在{word_min}-{word_max}字
4. 不要写集数标题
5. 保持剧本格式：【场景】、（动作）、角色名：台词、「旁白」
6. 保持原文的写作风格（除非用户要求改变风格）
7. 直接输出重写后的剧本内容"""

_ANALYZE_CHANGE_PROMPT = """你是一个小说结构分析师。判断用户的修改要求是否会影响后续章节。

判断标准：
- 结构性改动（影响后续）：改变剧情走向、角色生死、重大事件结果、核心设定变更、删除/新增重要角色
- 非结构性改动（不影响后续）：润色文字、调整对话、改善描写、修正细节错误、调整节奏

输出JSON：
{{"structural": true/false, "reason": "判断理由"}}"""


class WritingPipeline:
    """Orchestrates the 6-step chapter writing pipeline."""

    def __init__(self, provider: LLMProvider, root: Path, word_target: int = 2000) -> None:
        self.provider = provider
        self.root = root
        self.word_target = word_target
        self._paths = project_fs.project_paths(root)
        self._state_store = StateStore(root)
        self._contract_mgr = ContractManager(root)
        self._review_engine = ReviewEngine(provider)
        self._commit_service = CommitService(provider, root)

    async def write_chapter(
        self,
        chapter: int,
        *,
        outline: dict | None = None,
        mode: str = "default",
        on_step=None,
    ) -> bool:
        """Execute the full writing pipeline.

        Args:
            chapter: Chapter number to write.
            outline: Optional chapter outline dict.
            mode: "default" (full), "fast" (light review), "minimal" (format only).
            on_step: Optional callback fn(step_name: str) for progress reporting.

        Returns:
            True if chapter was successfully written and committed.
        """
        def _step(msg: str):
            info(msg)
            if on_step:
                on_step(msg)

        # Step 0: Preflight
        _step("Step 0: 预检...")
        state = self._state_store.load()
        if not state.project_info.title:
            error("项目未初始化。请先运行 'aznovel init'")
            return False

        # Step 1: Contract refresh
        _step("Step 1: 契约刷新...")
        master = self._contract_mgr.load_master_setting()
        if not master.genre:
            genre_template = load_genre(resolve_genre_alias(state.project_info.genre))
            master = self._contract_mgr.generate_master_setting(state, genre_template)
            self._contract_mgr.save_master_setting(master)

        chapter_brief = self._contract_mgr.generate_chapter_brief(
            chapter, state, master, outline
        )
        self._contract_mgr.save_chapter_brief(chapter_brief)

        review_contract = self._contract_mgr.generate_review_contract(
            chapter, state, master
        )
        self._contract_mgr.save_review_contract(review_contract)

        # Step 2: Context assembly
        _step("Step 2: 上下文组装...")
        previous_summary = self._load_previous_summary(chapter)
        brief_text = build_writing_brief(
            chapter_brief, master, state, previous_summary
        )

        # Step 3: Draft
        _step("Step 3: 生成初稿...")
        chapter_text = await self._draft(brief_text)
        if not chapter_text:
            error("初稿生成失败")
            return False

        word_count = count_chinese_chars(chapter_text)
        info(f"  初稿字数: {word_count}")

        # Step 4: Review
        if mode != "minimal":
            _step("Step 4: 审查...")
            review_result = await self._review_engine.review_chapter(
                chapter_text, review_contract
            )
            report = format_review_report(review_result)
            self._save_review_report(chapter, report)

            if not review_result.passed:
                warn(f"  发现 {review_result.blocking_count} 个阻断问题，尝试润色修复...")
                chapter_text = await self._polish(chapter_text, report)
                # Re-review after polish
                if mode == "default":
                    _step("  重新审查...")
                    review_result = await self._review_engine.review_chapter(
                        chapter_text, review_contract
                    )
                    report = format_review_report(review_result)
                    self._save_review_report(chapter, report)
        else:
            review_result = ReviewResult(chapter_number=chapter, passed=True)
            _step("Step 4: 跳过审查 (minimal 模式)")

        # Step 5: Commit
        _step("Step 5: 提交...")
        title = chapter_brief.title or f"第{chapter}章"
        commit = await self._commit_service.commit_chapter(
            chapter, chapter_text, title, review_result
        )
        info(f"  状态: {commit.status}")

        # Step 6: Save chapter file
        _step("Step 6: 保存章节...")
        self._save_chapter(chapter, title, chapter_text)

        success(f"第{chapter:03d}章写作完成！")
        return True

    async def _draft(self, brief_text: str) -> str:
        """Generate chapter draft from writing brief."""
        from aznovel.storage.template_loader import is_drama_genre, is_literary_genre

        state = self._state_store.load()
        genre = state.project_info.genre
        is_lit = is_literary_genre(genre)
        is_drama = is_drama_genre(genre)

        wmin = int(self.word_target * 0.8)
        wmax = int(self.word_target * 1.2)

        if is_drama:
            writer_type = "短剧编剧"
            extra_rules = _DRAFT_EXTRA_DRAMA
            prompt = _DRAFT_SYSTEM_PROMPT_DRAMA.format(
                word_min=wmin, word_max=wmax,
                extra_rules=extra_rules,
            )
        else:
            writer_type = "文学小说作家" if is_lit else "中文网文写手"
            extra_rules = _DRAFT_EXTRA_LITERARY if is_lit else _DRAFT_EXTRA_WEBNOVEL
            prompt = _DRAFT_SYSTEM_PROMPT.format(
                word_min=wmin, word_max=wmax,
                writer_type=writer_type, extra_rules=extra_rules,
            )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": brief_text},
        ]
        resp = await self.provider.chat(messages, max_tokens=8192)
        return resp.content.strip()

    async def _polish(self, chapter_text: str, review_report: str) -> str:
        """Polish chapter based on review findings."""
        from aznovel.storage.template_loader import is_drama_genre

        state = self._state_store.load()
        is_drama = is_drama_genre(state.project_info.genre)

        wmin = int(self.word_target * 0.8)
        wmax = int(self.word_target * 1.2)
        prompt_template = _POLISH_SYSTEM_PROMPT_DRAMA if is_drama else _POLISH_SYSTEM_PROMPT
        prompt = prompt_template.format(word_min=wmin, word_max=wmax)
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"## 审查报告\n{review_report}\n\n## 原文\n{chapter_text}",
            },
        ]
        resp = await self.provider.chat(messages, max_tokens=8192)
        return resp.content.strip()

    def _save_chapter(self, chapter: int, title: str, content: str) -> None:
        """Save chapter file to 正文/ directory."""
        path = self._paths["chapters_dir"] / chapter_filename(chapter)
        text = f"# {title}\n\n{content}\n"
        path.write_text(text, encoding="utf-8")
        logger.info(f"Chapter saved: {path}")

    def _save_review_report(self, chapter: int, report: str) -> None:
        """Save review report to 审查报告/ directory."""
        path = self._paths["reviews_dir"] / f"chapter_{chapter:03d}_review.md"
        path.write_text(report, encoding="utf-8")
        logger.info(f"Review report saved: {path}")

    def _load_previous_summary(self, chapter: int) -> str:
        """Load summary of the previous chapter from commit."""
        if chapter <= 1:
            return ""
        prev_commit_path = (
            self._paths["commits_dir"] / f"chapter_{chapter - 1:03d}.commit.json"
        )
        data = project_fs.load_json(prev_commit_path)
        return data.get("summary", "")

    async def analyze_change(self, chapter: int, modification: str) -> dict:
        """Analyze if a modification is structural (affects subsequent chapters)."""
        chapter_path = self._paths["chapters_dir"] / chapter_filename(chapter)
        if not chapter_path.exists():
            return {"structural": True, "reason": "章节不存在，需要新建"}

        original = chapter_path.read_text(encoding="utf-8")

        messages = [
            {"role": "system", "content": _ANALYZE_CHANGE_PROMPT},
            {"role": "user", "content": f"## 原章节内容\n{original}\n\n## 用户修改要求\n{modification}"},
        ]
        try:
            result = await self.provider.chat_json(messages, temperature=0.0)
            return result
        except Exception:
            return {"structural": True, "reason": "无法判断，默认视为结构性改动"}

    async def rewrite_chapter(
        self,
        chapter: int,
        modification: str,
        *,
        mode: str = "default",
        force_cascade: bool = False,
        on_step=None,
    ) -> tuple[bool, bool]:
        """Rewrite an existing chapter based on modification instructions.

        Returns:
            (success, was_cascaded): whether the rewrite succeeded and whether subsequent chapters were deleted.
        """
        # Load existing chapter
        chapter_path = self._paths["chapters_dir"] / chapter_filename(chapter)
        if not chapter_path.exists():
            error(f"第{chapter}章不存在，无法重写。请用 write 命令新建。")
            return False, False

        original_text = chapter_path.read_text(encoding="utf-8")
        # Strip title line if present
        lines = original_text.split("\n")
        if lines and lines[0].startswith("# "):
            original_text = "\n".join(lines[1:]).strip()

        # Check for subsequent chapters
        subsequent = self._get_subsequent_chapters(chapter)
        was_cascaded = False

        if subsequent and not force_cascade:
            # Analyze if change is structural
            info("分析修改影响...")
            analysis = await self.analyze_change(chapter, modification)
            is_structural = analysis.get("structural", True)
            reason = analysis.get("reason", "")

            if is_structural:
                warn(f"检测到结构性改动：{reason}")
                warn(f"以下后续章节将被删除：{', '.join(f'第{c}章' for c in subsequent)}")
                warn("这些章节需要在重写后重新生成。")
                was_cascaded = True
            else:
                info(f"改动类型：非结构性（{reason}）")
                info("后续章节不受影响，保持不变。")
        elif subsequent and force_cascade:
            warn(f"将删除后续章节：{', '.join(f'第{c}章' for c in subsequent)}")
            was_cascaded = True

        # Step 1: Rewrite the chapter
        info(f"正在重写第{chapter}章...")
        from aznovel.storage.template_loader import is_drama_genre

        state = self._state_store.load()
        is_drama = is_drama_genre(state.project_info.genre)

        wmin = int(self.word_target * 0.8)
        wmax = int(self.word_target * 1.2)
        prompt_template = _REWRITE_SYSTEM_PROMPT_DRAMA if is_drama else _REWRITE_SYSTEM_PROMPT
        prompt = prompt_template.format(word_min=wmin, word_max=wmax)

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"## 原文\n{original_text}\n\n## 修改要求\n{modification}"},
        ]
        resp = await self.provider.chat(messages, max_tokens=8192)
        new_text = resp.content.strip()

        if not new_text:
            error("重写失败：LLM 返回空内容")
            return False, False

        word_count = count_chinese_chars(new_text)
        info(f"  重写字数: {word_count}")

        # Step 2: Review (unless minimal)
        master = self._contract_mgr.load_master_setting()

        review_contract = self._contract_mgr.generate_review_contract(
            chapter, state, master
        )

        if mode != "minimal":
            info("审查重写内容...")
            review_result = await self._review_engine.review_chapter(
                new_text, review_contract
            )
            report = format_review_report(review_result)
            self._save_review_report(chapter, report)

            if not review_result.passed:
                warn(f"  发现 {review_result.blocking_count} 个阻断问题，尝试润色...")
                new_text = await self._polish(new_text, report)
        else:
            review_result = ReviewResult(chapter_number=chapter, passed=True)

        # Step 3: Delete subsequent chapters if cascaded
        if was_cascaded and subsequent:
            self._delete_subsequent_chapters(subsequent)
            # Reset progress
            state.progress.current_chapter = chapter
            self._state_store.save(state)
            info(f"已删除 {len(subsequent)} 个后续章节，进度已重置为第{chapter}章。")

        # Step 4: Commit the rewritten chapter
        chapter_brief = self._contract_mgr.generate_chapter_brief(
            chapter, state, master
        )
        title = chapter_brief.title or f"第{chapter}章"

        commit = await self._commit_service.commit_chapter(
            chapter, new_text, title, review_result
        )

        # Step 5: Save
        self._save_chapter(chapter, title, new_text)

        success(f"第{chapter}章重写完成！")
        return True, was_cascaded

    def _get_subsequent_chapters(self, chapter: int) -> list[int]:
        """Get list of chapter numbers after the given chapter."""
        chapters_dir = self._paths["chapters_dir"]
        if not chapters_dir.exists():
            return []
        subsequent = []
        for f in sorted(chapters_dir.glob("第*章.md")):
            num = extract_chapter_number(f.name)
            if num and num > chapter:
                subsequent.append(num)
        return subsequent

    def _delete_subsequent_chapters(self, chapters: list[int]) -> None:
        """Delete chapter files, commits, reviews, and contracts for given chapters."""
        for ch in chapters:
            # Delete chapter file
            ch_path = self._paths["chapters_dir"] / chapter_filename(ch)
            if ch_path.exists():
                ch_path.unlink()
                logger.info(f"Deleted chapter file: {ch_path}")

            # Delete commit
            commit_path = self._paths["commits_dir"] / f"chapter_{ch:03d}.commit.json"
            if commit_path.exists():
                commit_path.unlink()
                logger.info(f"Deleted commit: {commit_path}")

            # Delete review report
            review_path = self._paths["reviews_dir"] / f"chapter_{ch:03d}_review.md"
            if review_path.exists():
                review_path.unlink()
                logger.info(f"Deleted review: {review_path}")

            # Delete contracts
            for suffix in ["", ".review"]:
                contract_path = self._paths["contracts_dir"] / f"chapter_{ch:03d}{suffix}.json"
                if contract_path.exists():
                    contract_path.unlink()
                    logger.info(f"Deleted contract: {contract_path}")
