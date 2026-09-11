"""Writing pipeline - orchestrates the 6-step chapter writing flow."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
import re
from pathlib import Path

from aznovel.core.commit import CommitService
from aznovel.core.context import build_writing_brief
from aznovel.core.contract_manager import ContractManager
from aznovel.core.review_engine import ReviewEngine, format_review_report
from aznovel.llm.base import LLMProvider
from aznovel.models.contract import ChapterBrief, MasterSetting, ReviewContract
from aznovel.models.project import ProjectState
from aznovel.models.review import ReviewIssue, ReviewResult
from aznovel.storage import project_fs
from aznovel.storage.state_store import StateStore
from aznovel.storage.template_loader import load_genre, resolve_genre_alias
from aznovel.utils.rich_ui import console, error, info, panel, success, warn
from aznovel.utils.text import chapter_filename, count_chinese_chars, extract_chapter_number

logger = logging.getLogger(__name__)

_DRAFT_SYSTEM_PROMPT = """你是一个专业的中文{writer_type}。你的任务是根据写作任务书写一章小说。

写作规则：
1. **必须严格按照「本章剧情大纲」写作**——大纲中指定的角色、事件、场景必须全部出现在正文中，可以在大纲框架内自由发挥细节，但不可遗漏或替换大纲指定的核心内容
2. 大纲指定“事件发生”“公开事件”“结尾事件”时，必须写成当前章节中的直接场景；不要只用新闻推送、监控录像、回忆、传闻或他人口述替代
3. 资源稀缺、配给制、贫困、断粮等设定必须数量闭环；关键物资不能凭空增多，消耗的每一份都要有来源、代价和风险
4. 角色异变、被标记、觉醒、背叛等关键信息必须按大纲节奏递进；如果大纲要求“结尾发现线索”，正文中途只能埋异常线索，不能提前定性为全面同化或阵营转变
5. 只写本章大纲覆盖的剧情，结尾必须停在本章指定的悬念/状态；不要提前写后续章节的牺牲、逃离、解药见效、终极真相或结局
6. 字数控制在{word_min}-{word_max}字
7. 不要写章节标题（标题会单独处理）
8. 直接输出正文内容
9. 展示而非叙述（Show, don't tell）
{extra_rules}"""

_DRAFT_SYSTEM_PROMPT_DRAMA = """你是一个专业的短剧编剧。你的任务是根据写作任务书写一集短剧剧本。

写作规则：
1. 严格按照写作任务书的要求写作
2. 写作任务书指定“事件发生”“公开事件”“结尾事件”时，必须写成当前集中的直接场景；不要只用新闻推送、监控录像、回忆、传闻或他人口述替代
3. 资源稀缺、配给制、贫困、断粮等设定必须数量闭环；关键物资不能凭空增多，消耗的每一份都要有来源、代价和风险
4. 角色异变、被标记、觉醒、背叛等关键信息必须按大纲节奏递进；如果大纲要求“结尾发现线索”，正文中途只能埋异常线索，不能提前定性为全面同化或阵营转变
5. 只写本集任务书覆盖的剧情，结尾必须停在本集指定的悬念/状态；不要提前写后续集的牺牲、逃离、解药见效、终极真相或结局
6. 字数控制在{word_min}-{word_max}字
7. 不要写集数标题（标题会单独处理）
8. 直接输出剧本内容
9. 剧本格式：
   - 场景描述用【场景】标注
   - 角色动作用括号（）标注
   - 对话格式：角色名：台词内容
   - 旁白/画外音用「旁白」标注
10. 每集结尾必须有悬念钩子
11. 对话要短句为主，情绪张力强
12. 节奏要快，不要拖沓
13. 反转要合理但出人意料
14. 冲突要激烈，情绪要浓烈
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

_TAIL_REPAIR_SYSTEM_PROMPT = """你是一个严谨的小说尾段修复编辑。你的任务是只重写章节尾段，让章节回到大纲指定的结尾状态。

规则：
1. 只输出修复后的尾段正文，不要输出章节标题、说明、清单或Markdown
2. 必须承接“保留前文”的最后一句，不能重复保留前文
3. 只修复审查报告指出的章节越界、结尾过头、时间矛盾问题
4. 不要提前写后续章节事件，例如牺牲完成、成功逃离、解药见效、终极真相揭晓或结局落定
5. 如果大纲要求结尾停在包围、追兵到达、门被撞击、希望未兑现等悬念点，就必须停在那里
6. 如果血清/解药/抗性因子需要较长时间，不能让刚采集的样本几分钟内变成有效药剂
7. 禁止把唯一希望在本章物理毁灭，例如样本被吸干、试管碎裂、研究者当场死亡、主角已经逃出实验室
8. 如果大纲要求“包围”，严禁写成“攻破/入侵”：禁止气密门彻底倒塌、藤蔓漫过门槛、切断退路、探到操作台、把人物围在操作台前
9. 输出尾段长度控制在600-1200个中文字符，保持惊悚紧张，但不要解决本章以后才该解决的问题"""

_MICRO_EVIDENCE_PATCH_SYSTEM_PROMPT = """你是一个严谨的小说微补丁编辑。你只能替换审查报告点名的一小段证据文本。

规则：
1. 只输出JSON，不要输出Markdown或说明
2. old 必须完整等于用户给出的“待替换证据原文”
3. new 只能是一句、一个短语或一个短段，用于修复当前阻断问题
4. 不要改变剧情事件，不要新增人物动作链，不要提前推进后续章节
5. 如果问题是人物状态不符，就把词句改成符合大纲状态的动作或声音，例如继续研究、记录、操作仪器、压住恐惧等
6. 如果问题是因果解释冲突，就删除错误因果，改用正文已有道具、动作或环境线索解释，不要发明需要前文铺垫的新原因

输出JSON格式：
{"old": "待替换证据原文", "new": "替换后的短文本", "reason": "修复理由"}"""

_LOCAL_PATCH_SYSTEM_PROMPT = """你是一个严谨的小说局部修复编辑。根据审查报告为章节生成可程序应用的最小文本补丁。

规则：
1. 只输出JSON，不要输出正文全文、解释性Markdown或代码块
2. 每个补丁必须是原文中连续且唯一出现的 exact old 文本，以及替换后的 new 文本
3. old 必须逐字来自原文；不要改写 old，不要使用省略号
4. 优先修复 [BLOCKING]、critical、high 问题；每个阻断问题至少尝试生成一个补丁
5. 审查报告点名的证据句必须删除、替换或补足因果，不能原样保留
6. 允许使用段落级补丁修复人物动机、因果链、重复段落或设定矛盾，但不要整章重写
7. 如果报告指出人物行为矛盾，不要只增加心理描写；必须改掉矛盾台词/行为，或补足外部强制条件与因果链
8. 如果报告指出事件呈现方式偏离大纲（例如被写成回忆、录像、转述而不是现场事件），必须用补丁把对应段落改为直接发生的场景
9. 如果报告指出流程/制度/手续无法闭环，不要继续添加复杂解释；优先删除造成漏洞的手续细节，改成更简单、可核验的因果链
10. 如果无法安全局部修复，返回空 edits

输出JSON格式：
{
  "edits": [
    {"old": "原文中唯一出现的连续片段", "new": "替换后的片段", "reason": "修复的问题"}
  ]
}"""

_STRUCTURED_REPAIR_PLANNER_SYSTEM_PROMPT = """你是一个小说审查修复规划器。你的任务是把审查报告转成通用、可执行的小修复任务。

规则：
1. 只输出JSON，不要输出Markdown或解释
2. 不要依赖固定题材关键词；必须从“大纲/契约、审查报告、正文段落”中概括违反的通用约束
3. 优先处理 [BLOCKING]、critical、high 问题
4. paragraph_indexes 只能填写下方“编号正文段落”中存在的段落编号
5. 如果问题需要上下文才能修复，选择相邻的多个段落；不要选择整章
6. required_fix 必须说明“应该如何改”，不是只复述问题
7. success_criteria 必须是复审时可判断的具体条件

输出JSON格式：
{
  "tasks": [
    {
      "issue_id": "I1",
      "blocking": true,
      "category": "setting|logic|outline|character|ai_flavor|other",
      "violated_contract": "被违反的大纲、设定、人物或逻辑约束",
      "evidence": ["审查报告中的关键证据或原文片段"],
      "paragraph_indexes": [12, 13],
      "required_fix": "对这些段落应如何局部修复",
      "success_criteria": ["修复后必须满足的检查点"],
      "risk_notes": ["容易新增的问题"]
    }
  ]
}"""

_STRUCTURED_TASK_PATCH_SYSTEM_PROMPT = """你是一个严谨的小说局部补丁编辑。你根据一个结构化修复任务生成可程序应用的 exact old/new 补丁。

规则：
1. 只输出JSON，不要输出Markdown或说明
2. 每个 old 必须完整等于“允许替换的原文窗口”中的一个窗口，不能截断、拼接、改写或使用省略号
3. new 只能修复当前 repair task，不要顺手改其他问题
4. 保留原段落的叙事功能、人物关系、场景位置和章节节奏
5. 不要整章重写；优先段落级或相邻段落级替换
6. 若无法安全修复，返回空 edits

输出JSON格式：
{
  "edits": [
    {"old": "允许窗口中的完整原文", "new": "替换后的文本", "reason": "修复任务ID和理由"}
  ]
}"""

_REWRITE_REVIEW_REPORT_MAX_CHARS = 16000
_LOCAL_PATCH_REPORT_MAX_CHARS = 12000
_LOCAL_PATCH_MAX_EDITS = 8
_STRUCTURED_REPAIR_MAX_TASKS = 4
_STRUCTURED_REPAIR_MAX_EDITS = 3
_STRUCTURED_REPAIR_TEXT_MAX_CHARS = 18000
_LOCAL_PATCH_SINGLE_BLOCKER_MAX_EDITS = 3
_PATCH_REJECT_STREAK_LIMIT = 4
_FOCUSED_PATCH_MAX_WINDOWS = 6
_FOCUSED_PATCH_MAX_EDITS = 3
_FOCUSED_PATCH_SINGLE_BLOCKER_MAX_EDITS = 2
_PATCH_REJECT_STREAK_LIMIT_SINGLE_BLOCKER = 3
_FOCUSED_PATCH_REJECT_STREAK_LIMIT = 2
_PATCH_GENERATION_TIMEOUT = 120.0
_AUTO_REPAIR_MAX_ROUNDS = 6
AUTO_RUN_REPAIR_ATTEMPTS_DEFAULT = 5
_FULL_POLISH_MIN_BLOCKERS = 2
_REPAIR_SAME_BLOCKER_RISK_TOLERANCE = 25
_FINAL_SAFE_REPAIR_MAX_CHANGE_RATIO = 0.12
_FINAL_SAFE_REPAIR_MAX_CHANGE_CHARS = 1000


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
        if outline is None:
            outline = self._load_chapter_outline(chapter)

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
            chapter, state, master, chapter_brief=chapter_brief
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
        report = ""
        if mode != "minimal":
            _step("Step 4: 审查...")
            review_result = await self._review_engine.review_chapter(
                chapter_text, review_contract
            )
            report = format_review_report(review_result)

            if not review_result.passed:
                if mode == "default":
                    chapter_text, review_result, report = await self._repair_review_failures(
                        chapter_text,
                        review_result,
                        review_contract,
                        report,
                        chapter=chapter,
                        outline=outline,
                        known_entities=self._known_entity_names(state),
                        review_step_message="  重新审查...",
                        on_step=_step,
                    )
                else:
                    warn(f"  发现 {review_result.blocking_count} 个阻断问题，按审查报告润色修复...")
                    chapter_text = await self._polish(
                        chapter_text,
                        report,
                        chapter=chapter,
                        outline=outline,
                        known_entities=self._known_entity_names(state),
                    )
        else:
            review_result = ReviewResult(chapter_number=chapter, passed=True)
            _step("Step 4: 跳过审查 (minimal 模式)")

        title = chapter_brief.title or f"第{chapter}章"
        if not review_result.passed:
            candidate_path = self._save_candidate(chapter, title, chapter_text, report)
            warn(
                f"第{chapter:03d}章候选稿未通过审查，已保存为候选稿，正式正文未覆盖: {candidate_path}"
            )
            return False

        if report:
            self._save_review_report(chapter, report)

        # Step 5: Commit
        _step("Step 5: 提交...")
        commit = await self._commit_service.commit_chapter(
            chapter, chapter_text, title, review_result
        )
        info(f"  状态: {commit.status}")

        # Step 6: Save chapter file
        _step("Step 6: 保存章节...")
        self._save_chapter(chapter, title, chapter_text)
        self._clear_candidate(chapter)

        if commit.status == "accepted":
            success(f"第{chapter:03d}章写作完成！")
            return True

        warn(f"第{chapter:03d}章已保存，但审查未通过，请先修复阻断问题。")
        return False

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

    def _repair_strategy_notes(self, review_report: str) -> list[str]:
        """Derive cross-genre tactics from recurring review failure patterns."""
        notes: list[str] = []
        if re.search(r"(新闻|推送|报道|录像|回忆|转述|间接|口述)", review_report) and re.search(
            r"(大纲|直接|现场|发生|呈现|亲历|结尾)", review_report
        ):
            notes.append(
                "大纲指定的关键事件不能只通过新闻、推送、录像、回忆或他人口述完成；必须改成当前叙事时空里的直接场景，让角色现场目睹、卷入或被迫应对。"
            )
        if re.search(r"(资源|存量|数量|预算|配给|贫困|断粮|库存|不可能|不足|过多)", review_report):
            notes.append(
                "资源、库存、时间、钱款或物资不足类冲突要用数量闭合解决：删除凭空增加的存量，明确来源、消耗和剩余，不要用新的解释扩大漏洞。"
            )
        if re.search(r"(AI味|ai_flavor|解释性|总结|归纳|破折号|比喻)", review_report):
            notes.append(
                "若审查指出展示后解释、总结归纳或破折号式比喻有 AI 味，必须删掉结论性解释句，改为角色观察到的具体细节、动作、迟疑或选择，让读者从现场信息中自行得出结论。"
            )
        if re.search(r"(身份|职业|专业|能力|设定|规则|边界|体系)", review_report):
            notes.append(
                "若审查指出身份、职业、能力或世界观规则越界，必须先抽取报告里的限制条件，再把行为、信息来源和推理过程收回到该限制内。"
            )
        if re.search(r"(OOC|人物.*不符|惊恐|恐惧)", review_report) and re.search(
            r"(平静|没有尖叫|没有逃跑|不害怕)", review_report
        ):
            notes.append(
                "若审查指出角色应惊恐却表现平静，必须删除否定恐惧或平静接受的表达，改为通过后退、失控、逃离、呼吸/手部反应等具体动作表现惊恐。"
            )
        if re.search(r"(称呼.*不一致|前后不一致|名字.*不一致|叙事断裂)", review_report):
            notes.append(
                "若审查指出人物称谓前后不一致，必须以前文首次出现的名称为准统一全章称谓，不要创造相近的新名字。"
            )
        if re.search(r"(提前|过早|节奏|结尾才|信息暴露|悬念)", review_report):
            notes.append(
                "若审查指出信息暴露过早，必须把明确结论降级成可疑但未定性的线索；直到大纲指定节点再揭示结论。"
            )
        if re.search(r"(结尾|大纲|后续|提前|第[0-9一二三四五六七八九十]+章)", review_report) and re.search(
            r"(越界|推进|已经发生|结局|后续|提前|完成|落定)",
            review_report,
        ):
            notes.append(
                "若审查指出章节越界或结尾推进过头，必须把剧情收回到本章大纲指定的悬念点，删除或改写提前完成的后续事件。"
            )
        if re.search(r"(时间|时长|几分钟|几小时|倒计时|来不及|撑多久)", review_report) and re.search(
            r"(矛盾|冲突|不成立|过快|过慢|无法)", review_report
        ):
            notes.append(
                "若审查指出时间线或耗时矛盾，必须统一时长、等待过程和结果触发条件；无法闭合时优先删掉过精确的时间承诺。"
            )
        if re.search(r"(人物状态|求生|工作|研究|任务|状态)", review_report) and re.search(
            r"(绝望|干呕|崩溃|瘫坐|放弃)", review_report
        ):
            notes.append(
                "若审查指出人物状态偏离当前任务，优先替换证据句里的崩溃、放弃或过度情绪化动作，改为仍在执行任务但承受压力的可见行为。"
            )
        return notes

    def _build_polish_instruction(
        self,
        *,
        chapter_text: str,
        review_report: str,
        chapter: int | None = None,
        outline: dict | None = None,
        known_entities: list[str] | None = None,
    ) -> str:
        """Build a targeted polish brief from concrete review findings."""
        parts = ["# 润色修复任务书"]

        if outline:
            outline_lines = []
            if chapter is not None:
                outline_lines.append(f"- 章节: 第{chapter:03d}章")
            if outline.get("title"):
                outline_lines.append(f"- 标题: {outline['title']}")
            if outline.get("goal"):
                outline_lines.append(f"- 本章目标: {outline['goal']}")
            if outline.get("summary"):
                outline_lines.append(f"- 剧情大纲: {outline['summary']}")
            if outline.get("key_nodes"):
                outline_lines.append("- 关键节点:")
                outline_lines.extend(f"  - {item}" for item in outline["key_nodes"])
            parts.append("## 本章大纲（修复时不可偏离）\n" + "\n".join(outline_lines))

        if known_entities:
            parts.append("## 已知实体名（必须保留精确称谓）\n" + "、".join(known_entities))

        parts.append("## 审查报告（必须逐条修复）\n" + review_report)
        strategy_notes = self._repair_strategy_notes(review_report)
        if strategy_notes:
            parts.append(
                "## 自动诊断修复策略\n"
                + "\n".join(f"- {note}" for note in strategy_notes)
            )
        parts.append(
            "## 修复规则\n"
            "1. 只修复审查报告指出的问题，尤其是 [BLOCKING]、critical、high 问题。\n"
            "2. 不要重新规划整章，不要替换已符合大纲的核心事件、角色和场景。\n"
            "3. 被报告点名的证据句必须删除、改写或补足上下文，不能原样保留。\n"
            "4. 如果报告指出人物行为矛盾或 OOC，不要只增加心理描写；必须改掉矛盾台词/行为，或补足外部强制条件、选择约束和因果链。\n"
            "5. 如果报告指出事件呈现方式偏离大纲（例如写成回忆、录像、新闻转述而不是现场事件），必须把对应段落改成直接发生的场景。\n"
            "6. 如果报告指出流程、制度或手续无法闭环，不要继续添加复杂解释；优先删除造成漏洞的手续细节，改成更简单、可核验的因果链。\n"
            "7. 修复 AI 味时，用具体动作、物象、对话和感官细节替代抽象判断、排比推演和套路比喻。\n"
            "8. 大纲或已知实体中出现的角色、组织、地点、物品名称必须精确保留；不要用“教授”“儿子”“公司”等泛称替代具体专名。\n"
            "9. 如果问题是信息暴露节奏过早，必须删掉提前定性的词句，把它改成疑似线索或误判空间，不能用更多解释继续坐实。\n"
            "10. 如果问题是章节越界，必须删除或改写提前发生的后续章节事件，让本章停在大纲指定结尾，不要用解释补洞。\n"
            "11. 输出完整修复后的正文，是为了覆盖保存；但内容改动应尽量局部、克制。"
        )
        parts.append("## 原文\n" + chapter_text)

        return "\n\n".join(parts)

    async def _polish(
        self,
        chapter_text: str,
        review_report: str,
        *,
        chapter: int | None = None,
        outline: dict | None = None,
        known_entities: list[str] | None = None,
    ) -> str:
        """Polish chapter based on review findings."""
        from aznovel.storage.template_loader import is_drama_genre

        state = self._state_store.load()
        is_drama = is_drama_genre(state.project_info.genre)

        wmin = int(self.word_target * 0.8)
        wmax = int(self.word_target * 1.2)
        prompt_template = _POLISH_SYSTEM_PROMPT_DRAMA if is_drama else _POLISH_SYSTEM_PROMPT
        prompt = prompt_template.format(word_min=wmin, word_max=wmax)
        polish_instruction = self._build_polish_instruction(
            chapter_text=chapter_text,
            review_report=review_report,
            chapter=chapter,
            outline=outline,
            known_entities=known_entities,
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": polish_instruction},
        ]
        resp = await self.provider.chat(messages, max_tokens=8192)
        return resp.content.strip()

    def _build_local_patch_instruction(
        self,
        *,
        chapter_text: str,
        review_report: str,
        chapter: int | None = None,
        outline: dict | None = None,
        known_entities: list[str] | None = None,
    ) -> str:
        """Build a prompt for machine-checkable local text edits."""
        parts = ["# 局部补丁任务"]

        if outline:
            outline_lines = []
            if chapter is not None:
                outline_lines.append(f"- 章节: 第{chapter:03d}章")
            if outline.get("title"):
                outline_lines.append(f"- 标题: {outline['title']}")
            if outline.get("goal"):
                outline_lines.append(f"- 本章目标: {outline['goal']}")
            if outline.get("summary"):
                outline_lines.append(f"- 剧情大纲: {outline['summary']}")
            parts.append("## 本章大纲\n" + "\n".join(outline_lines))

        if known_entities:
            parts.append("## 已知实体名（补丁后必须保留精确称谓）\n" + "、".join(known_entities))

        report = review_report
        if len(report) > _LOCAL_PATCH_REPORT_MAX_CHARS:
            report = report[:_LOCAL_PATCH_REPORT_MAX_CHARS] + "\n\n[审查报告过长，后文已截断。]"
        parts.append("## 最新审查报告\n" + report)
        strategy_notes = self._repair_strategy_notes(review_report)
        if strategy_notes:
            parts.append(
                "## 自动诊断补丁策略\n"
                + "\n".join(f"- {note}" for note in strategy_notes)
            )
        parts.append(
            "## 补丁要求\n"
            "- 生成不超过 8 个 old/new 补丁。\n"
            "- old 必须来自下方原文，且在原文中只出现一次。\n"
            "- new 可以短于 old，也可以为空字符串以删除冗余句，但不得引入新矛盾。\n"
            "- 对每个 [BLOCKING] 问题，至少尝试一个补丁，直接替换或删除报告中引用的证据句。\n"
            "- 人物动机、因果链、重复段落、设定矛盾可以使用段落级补丁；修复行为矛盾时，必须改掉矛盾台词/行为或补足外部强制条件。\n"
            "- 如果报告指出事件被写成录像/回忆/转述而不是现场发生，用段落补丁改为直接场景。\n"
            "- 如果报告指出手续、规则或核验流程无法闭环，优先删掉造成漏洞的流程细节，改成简单可闭环的因果。\n"
            "- 如果报告指出信息暴露节奏过早，必须把提前定性的词句降级为疑似线索；不要增加解释来坐实它。\n"
            "- 如果报告指出章节越界，必须把本章结尾收回到大纲指定的悬念点，删除或替换提前发生的后续章事件。\n"
            "- 不要为了修复局部问题而重写整章。"
        )
        parts.append("## 原文\n" + chapter_text)

        return "\n\n".join(parts)

    def _apply_text_edits(self, text: str, edits: list[dict]) -> tuple[str, int, list[str]]:
        """Apply exact, unique old->new edits. Unsafe edits are skipped."""
        result = text
        applied = 0
        errors: list[str] = []

        for idx, edit in enumerate(edits[:_LOCAL_PATCH_MAX_EDITS], 1):
            old = str(edit.get("old", ""))
            new = str(edit.get("new", ""))
            reason = str(edit.get("reason", "")).strip()

            if not old:
                errors.append(f"edit {idx}: old 为空")
                continue
            if old == new:
                errors.append(f"edit {idx}: old 与 new 相同")
                continue

            count = result.count(old)
            if count != 1:
                label = f" ({reason})" if reason else ""
                errors.append(f"edit {idx}{label}: old 匹配次数为 {count}，跳过")
                continue

            result = result.replace(old, new, 1)
            applied += 1

        return result, applied, errors

    def _numbered_paragraphs(self, chapter_text: str) -> list[tuple[int, str]]:
        """Split chapter text into stable 1-based paragraph numbers."""
        paragraphs = [
            part.strip()
            for part in re.split(r"\n\s*\n", chapter_text)
            if part.strip()
        ]
        return [(index, paragraph) for index, paragraph in enumerate(paragraphs, 1)]

    def _format_numbered_paragraphs(
        self,
        paragraphs: list[tuple[int, str]],
        *,
        max_chars: int = _STRUCTURED_REPAIR_TEXT_MAX_CHARS,
    ) -> str:
        """Format numbered paragraphs without exceeding the planner prompt budget."""
        lines: list[str] = []
        total = 0
        for index, paragraph in paragraphs:
            chunk = f"[P{index}]\n{paragraph}"
            if total + len(chunk) > max_chars:
                lines.append(
                    f"[正文过长，后续 {len(paragraphs) - index + 1} 段已省略；优先修复上方审查证据指向的段落。]"
                )
                break
            lines.append(chunk)
            total += len(chunk)
        return "\n\n".join(lines)

    def _build_structured_repair_task_instruction(
        self,
        *,
        chapter_text: str,
        review_report: str,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
    ) -> str:
        """Build a generic LLM planning prompt from review report and numbered text."""
        parts = ["# 结构化修复规划输入"]
        if outline:
            outline_lines = [f"- 章节: 第{chapter:03d}章"]
            for key, label in (
                ("title", "标题"),
                ("goal", "本章目标"),
                ("summary", "剧情大纲"),
                ("ending_feeling", "结尾目标"),
            ):
                if outline.get(key):
                    outline_lines.append(f"- {label}: {outline[key]}")
            if outline.get("key_nodes"):
                outline_lines.append("- 关键节点:")
                outline_lines.extend(f"  - {item}" for item in outline["key_nodes"])
            parts.append("## 本章大纲/契约\n" + "\n".join(outline_lines))

        if known_entities:
            parts.append("## 已知实体名\n" + "、".join(known_entities))

        report = review_report
        if len(report) > _LOCAL_PATCH_REPORT_MAX_CHARS:
            report = report[:_LOCAL_PATCH_REPORT_MAX_CHARS] + "\n\n[审查报告过长，后文已截断。]"
        parts.append("## 审查报告\n" + report)

        paragraphs = self._numbered_paragraphs(chapter_text)
        parts.append("## 编号正文段落\n" + self._format_numbered_paragraphs(paragraphs))
        parts.append(
            "## 规划要求\n"
            "- 把每个阻断/高风险问题转成 repair task。\n"
            "- paragraph_indexes 必须指向最小可修复段落窗口；如果证据是综合描述，也要根据正文段落定位。\n"
            "- 不要提出整章重写，不要依赖题材关键词规则。"
        )
        return "\n\n".join(parts)

    def _valid_repair_tasks(
        self,
        data: dict,
        *,
        paragraph_count: int,
    ) -> list[dict]:
        """Normalize LLM repair tasks and discard invalid paragraph references."""
        raw_tasks = data.get("tasks", [])
        if not isinstance(raw_tasks, list):
            return []

        tasks: list[dict] = []
        for index, raw_task in enumerate(raw_tasks[:_STRUCTURED_REPAIR_MAX_TASKS], 1):
            if not isinstance(raw_task, dict):
                continue
            raw_indexes = raw_task.get("paragraph_indexes", [])
            if not isinstance(raw_indexes, list):
                raw_indexes = [raw_indexes]
            paragraph_indexes: list[int] = []
            for value in raw_indexes:
                try:
                    paragraph_index = int(value)
                except (TypeError, ValueError):
                    continue
                if 1 <= paragraph_index <= paragraph_count and paragraph_index not in paragraph_indexes:
                    paragraph_indexes.append(paragraph_index)
            if not paragraph_indexes:
                continue

            task = dict(raw_task)
            task["issue_id"] = str(task.get("issue_id") or f"I{index}")
            task["blocking"] = bool(task.get("blocking", False))
            task["paragraph_indexes"] = paragraph_indexes
            task["required_fix"] = str(task.get("required_fix", "")).strip()
            if not task["required_fix"]:
                continue
            tasks.append(task)

        tasks.sort(key=lambda item: (not item.get("blocking", False), min(item["paragraph_indexes"])))
        return tasks

    async def _generate_structured_repair_tasks(
        self,
        chapter_text: str,
        review_report: str,
        *,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
    ) -> list[dict]:
        """Ask the model to convert review feedback into generic repair tasks."""
        paragraphs = self._numbered_paragraphs(chapter_text)
        if not paragraphs:
            return []

        instruction = self._build_structured_repair_task_instruction(
            chapter_text=chapter_text,
            review_report=review_report,
            chapter=chapter,
            outline=outline,
            known_entities=known_entities,
        )
        messages = [
            {"role": "system", "content": _STRUCTURED_REPAIR_PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ]
        try:
            task_data = await asyncio.wait_for(
                self.provider.chat_json(messages, temperature=0.0, max_tokens=4096),
                timeout=_PATCH_GENERATION_TIMEOUT,
            )
        except Exception as exc:
            warn(f"  结构化修复规划失败: {exc}")
            return []

        tasks = self._valid_repair_tasks(task_data, paragraph_count=len(paragraphs))
        if not tasks:
            warn("  未生成可执行的结构化修复任务。")
        return tasks

    def _structured_task_windows(
        self,
        chapter_text: str,
        task: dict,
    ) -> list[str]:
        """Build exact replacement windows around task paragraph indexes."""
        paragraphs = self._numbered_paragraphs(chapter_text)
        if not paragraphs:
            return []
        paragraph_map = {index: paragraph for index, paragraph in paragraphs}
        indexes = [
            value
            for value in task.get("paragraph_indexes", [])
            if isinstance(value, int) and value in paragraph_map
        ]
        if not indexes:
            return []

        first = min(indexes)
        last = max(indexes)
        paragraph_count = len(paragraphs)
        spans = [
            (first, last),
            (max(1, first - 1), last),
            (first, min(paragraph_count, last + 1)),
            (max(1, first - 1), min(paragraph_count, last + 1)),
        ]
        spans.extend((index, index) for index in indexes)

        windows: list[str] = []
        seen: set[str] = set()
        for start, end in spans:
            parts = [paragraph_map[index] for index in range(start, end + 1) if index in paragraph_map]
            window = "\n\n".join(parts).strip()
            if not window or window in seen:
                continue
            seen.add(window)
            windows.append(window)
            if len(windows) >= _FOCUSED_PATCH_MAX_WINDOWS:
                break
        return windows

    def _build_structured_task_patch_instruction(
        self,
        *,
        task: dict,
        windows: list[str],
        chapter_text: str,
        outline: dict | None,
        known_entities: list[str],
    ) -> str:
        """Build the task-level exact patch prompt."""
        parts = ["# 结构化局部补丁任务"]
        if outline:
            outline_bits = []
            for key, label in (("summary", "剧情大纲"), ("goal", "本章目标"), ("ending_feeling", "结尾目标")):
                if outline.get(key):
                    outline_bits.append(f"- {label}: {outline[key]}")
            if outline_bits:
                parts.append("## 本章大纲/契约\n" + "\n".join(outline_bits))
        if known_entities:
            parts.append("## 已知实体名\n" + "、".join(known_entities))

        parts.append(
            "## Repair Task JSON\n"
            + json.dumps(task, ensure_ascii=False, indent=2)
        )
        window_lines = [
            f"### 窗口 {index}\n{window}"
            for index, window in enumerate(windows, 1)
        ]
        parts.append("## 允许替换的原文窗口\n" + "\n\n".join(window_lines))
        parts.append(
            "## 完整原文（仅用于理解前后文，不可整章重写）\n"
            + chapter_text[:_STRUCTURED_REPAIR_TEXT_MAX_CHARS]
        )
        return "\n\n".join(parts)

    async def _generate_structured_task_edits(
        self,
        chapter_text: str,
        task: dict,
        *,
        outline: dict | None,
        known_entities: list[str],
    ) -> list[dict]:
        """Ask the model for exact edits for one structured repair task."""
        windows = self._structured_task_windows(chapter_text, task)
        if not windows:
            return []
        instruction = self._build_structured_task_patch_instruction(
            task=task,
            windows=windows,
            chapter_text=chapter_text,
            outline=outline,
            known_entities=known_entities,
        )
        messages = [
            {"role": "system", "content": _STRUCTURED_TASK_PATCH_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ]
        try:
            patch_data = await asyncio.wait_for(
                self.provider.chat_json(messages, temperature=0.0, max_tokens=4096),
                timeout=_PATCH_GENERATION_TIMEOUT,
            )
        except Exception as exc:
            warn(f"  结构化任务补丁生成失败: {exc}")
            return []

        edits = patch_data.get("edits", [])
        if not isinstance(edits, list) or not edits:
            return []
        return edits[:_STRUCTURED_REPAIR_MAX_EDITS]

    def _blocking_report_excerpt(self, review_report: str) -> str:
        """Keep blocking issue blocks when possible, falling back to full report."""
        blocks: list[str] = []
        current: list[str] = []
        current_is_blocking = False

        for line in review_report.splitlines():
            if line.startswith("### "):
                if current and current_is_blocking:
                    blocks.append("\n".join(current).strip())
                current = [line]
                current_is_blocking = "[BLOCKING]" in line
                continue
            if current:
                current.append(line)
                if "[BLOCKING]" in line:
                    current_is_blocking = True

        if current and current_is_blocking:
            blocks.append("\n".join(current).strip())

        if not blocks:
            return review_report
        return "\n\n".join(blocks)

    def _review_evidence_fragments(self, review_report: str) -> list[str]:
        """Extract searchable snippets from Markdown evidence quotes."""
        fragments: list[str] = []
        for raw in re.findall(r"^\s*-\s*\*\*证据\*\*:\s*>?\s*(.+)$", review_report, re.MULTILINE):
            value = raw.strip(" >\t\r\n“”\"'")
            if 6 <= len(value) <= 220:
                fragments.append(value)
            for quoted in re.findall(r"[‘“\"]([^’”\"]{4,220})[’”\"]", raw):
                value = quoted.strip()
                if len(value) >= 6:
                    fragments.append(value[:80])
            for part in re.split(r"[。！？!?；;，,]|……|\.\.\.", raw):
                value = part.strip(" >\t\r\n“”\"'")
                if len(value) >= 6:
                    fragments.append(value[:40])
        for raw in re.findall(r"^\s*>\s*(.+)$", review_report, re.MULTILINE):
            value = raw.strip(" >\t\r\n“”\"'")
            if 6 <= len(value) <= 220:
                fragments.append(value)
            for quoted in re.findall(r"[‘“\"]([^’”\"]{4,220})[’”\"]", raw):
                value = quoted.strip()
                if len(value) >= 6:
                    fragments.append(value[:80])
            for part in re.split(r"[。！？!?；;，,]|……|\.\.\.", raw):
                value = part.strip(" >\t\r\n“”\"'")
                if len(value) >= 6:
                    fragments.append(value[:40])

        seen: set[str] = set()
        unique: list[str] = []
        for item in fragments:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        return unique

    def _review_search_terms(self, review_report: str, known_entities: list[str]) -> list[str]:
        """Extract short search terms from the current report instead of fixed story lore."""
        candidates: list[str] = []
        candidates.extend(name for name in known_entities if name and name in review_report)

        for quoted in re.findall(r"[‘“\"《「『]([^’”\"》」』]{2,80})[’”\"》」』]", review_report):
            for part in re.split(r"[。！？!?；;，,\s、：:（）()\[\]【】]", quoted):
                value = part.strip()
                if 2 <= len(value) <= 18:
                    candidates.append(value)

        candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9_/-]{1,24}", review_report))

        stopwords = {
            "问题",
            "描述",
            "证据",
            "正文",
            "大纲",
            "要求",
            "实际",
            "情况",
            "修复",
            "候选稿",
            "当前",
            "章节",
            "阻断",
            "审查",
            "报告",
            "指出",
            "导致",
            "因为",
            "但是",
            "不能",
            "必须",
            "没有",
            "需要",
            "属于",
            "存在",
            "如果",
            "已经",
            "应该",
        }
        for token in re.findall(r"[\u4e00-\u9fff]{2,8}", review_report):
            if token in stopwords:
                continue
            if any(token.startswith(prefix) for prefix in ("第", "问题", "描述", "证据")):
                continue
            candidates.append(token)

        seen: set[str] = set()
        terms: list[str] = []
        for item in candidates:
            value = item.strip()
            if len(value) < 2 or value in seen:
                continue
            seen.add(value)
            terms.append(value)
            if len(terms) >= 24:
                break
        return terms

    def _focused_patch_windows(
        self,
        chapter_text: str,
        review_report: str,
        *,
        known_entities: list[str],
    ) -> list[str]:
        """Pick exact paragraphs most likely responsible for current blockers."""
        blocking_report = self._blocking_report_excerpt(review_report)
        evidence_fragments = self._review_evidence_fragments(blocking_report)

        entities_in_report = [
            name for name in known_entities if name and name in blocking_report
        ]
        terms = self._review_search_terms(blocking_report, known_entities)
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", chapter_text) if part.strip()]
        scored: list[tuple[int, int, str]] = []

        for index, paragraph in enumerate(paragraphs):
            score = 0
            for fragment in evidence_fragments:
                if fragment and fragment in paragraph:
                    score += 8
            for name in entities_in_report:
                if name in paragraph:
                    score += 2
            for term in terms:
                if term in paragraph:
                    score += 1
            if score:
                scored.append((score, index, paragraph))

        scored.sort(key=lambda item: (-item[0], item[1]))
        windows: list[str] = []
        seen: set[str] = set()
        for _, index, paragraph in scored:
            candidates = [
                paragraph,
                "\n\n".join(paragraphs[index:index + 2]),
                "\n\n".join(paragraphs[max(0, index - 1):index + 2]),
            ]
            for candidate in candidates:
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                windows.append(candidate)
                if len(windows) >= _FOCUSED_PATCH_MAX_WINDOWS:
                    break
            if len(windows) >= _FOCUSED_PATCH_MAX_WINDOWS:
                break
        return windows

    def _build_focused_patch_instruction(
        self,
        *,
        chapter_text: str,
        review_report: str,
        windows: list[str],
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
    ) -> str:
        """Build a constrained patch task around the paragraphs tied to blockers."""
        parts = ["# 聚焦阻断补丁任务"]

        if outline:
            outline_lines = [f"- 章节: 第{chapter:03d}章"]
            if outline.get("title"):
                outline_lines.append(f"- 标题: {outline['title']}")
            if outline.get("goal"):
                outline_lines.append(f"- 本章目标: {outline['goal']}")
            if outline.get("summary"):
                outline_lines.append(f"- 剧情大纲: {outline['summary']}")
            if outline.get("key_nodes"):
                outline_lines.append("- 关键节点:")
                outline_lines.extend(f"  - {item}" for item in outline["key_nodes"])
            if outline.get("ending_feeling"):
                outline_lines.append(f"- 结尾目标: {outline['ending_feeling']}")
            parts.append("## 本章大纲\n" + "\n".join(outline_lines))

        if known_entities:
            parts.append("## 已知实体名（补丁后必须保留精确称谓）\n" + "、".join(known_entities))

        blocking_report = self._blocking_report_excerpt(review_report)
        parts.append("## 当前阻断问题\n" + blocking_report)
        strategy_notes = self._repair_strategy_notes(blocking_report)
        if strategy_notes:
            parts.append(
                "## 自动诊断补丁策略\n"
                + "\n".join(f"- {note}" for note in strategy_notes)
            )

        window_lines: list[str] = []
        for index, window in enumerate(windows, 1):
            window_lines.append(f"### 窗口 {index}\n{window}")
        parts.append("## 允许替换的原文窗口\n" + "\n\n".join(window_lines))
        parts.append(
            "## 输出要求\n"
            "- 只输出JSON，格式为 {\"edits\":[{\"old\":\"...\",\"new\":\"...\",\"reason\":\"...\"}]}。\n"
            "- old 必须完整等于上方某一个“允许替换的原文窗口”，不得截断、拼接或改写。\n"
            "- 如果单段窗口不足以修复因果或视角问题，优先选择包含相邻上下文的多段窗口。\n"
            "- new 只修复当前阻断问题，保持本段功能与前后剧情衔接；不要改写无关事件。\n"
            "- 如果报告指出视角、位置或感知条件冲突，new 必须让角色所在位置、可见范围和认知结果同时成立。\n"
            "- 如果报告指出设定、能力或规则边界被越权，new 必须把信息来源、能力效果和因果链收回到审查报告允许的范围内。\n"
            "- 如果问题是信息暴露过早，new 必须把明确结论降级成暧昧线索；不要新增设定解释来坐实结论。\n"
            "- 如果任何窗口都不能安全修复，返回空 edits。"
        )
        parts.append("## 完整原文（用于理解上下文，不可整章重写）\n" + chapter_text)
        return "\n\n".join(parts)

    def _apply_deterministic_review_patches(
        self,
        text: str,
        review_report: str,
    ) -> tuple[str, int]:
        """Apply only mechanical repairs that do not depend on story content."""
        result = text
        applied = 0

        if re.search(r"(称呼.*不一致|前后不一致|名字.*不一致|叙事断裂)", review_report):
            names = re.findall(r"老[\u4e00-\u9fff]", review_report)
            if len(names) >= 2:
                canonical = names[0]
                for wrong in names[1:]:
                    if wrong == canonical:
                        continue
                    count = result.count(wrong)
                    if count:
                        result = result.replace(wrong, canonical)
                        applied += count

        return result, applied

    def _outline_text(self, outline: dict | None) -> str:
        """Flatten outline fields into searchable text for guard checks."""
        if not outline:
            return ""
        parts: list[str] = []
        for key in ("title", "goal", "summary", "ending_feeling"):
            value = outline.get(key)
            if value:
                parts.append(str(value))
        for key in ("key_nodes", "must_cover"):
            value = outline.get(key)
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
        return "\n".join(parts)

    def _known_entity_names(self, state: ProjectState) -> list[str]:
        """Return deduplicated entity names, including the protagonist."""
        names = [state.protagonist.name] + [entity.name for entity in state.entities]
        seen: set[str] = set()
        result: list[str] = []
        for name in names:
            value = name.strip() if name else ""
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _entity_guard_violations(
        self,
        *,
        reference_text: str,
        candidate_text: str,
        outline: dict | None,
        known_entities: list[str],
    ) -> list[str]:
        """Detect accidental deletion of required entity names during repair."""
        context = reference_text + "\n" + self._outline_text(outline)
        violations: list[str] = []
        for name in sorted({item.strip() for item in known_entities if item and len(item.strip()) >= 2}):
            if name in context and name not in candidate_text:
                violations.append(f"候选稿丢失必需实体名：{name}")
        return violations

    def _has_research_material(self, text: str) -> bool:
        """Detect explicit research-material props required by some outlines."""
        return bool(
            re.search(
                r"(研究资料|实验记录|研究记录|资料袋|数据芯片|数据盘|硬盘|U盘|档案|手稿|配方页|实验数据)",
                text,
            )
        )

    def _outline_required_object_violations(
        self,
        *,
        candidate_text: str,
        outline: dict | None,
    ) -> list[str]:
        """Detect required outline props that are easy for reviewers to miss."""
        outline_text = self._outline_text(outline)
        violations: list[str] = []
        if "研究资料" in outline_text and not self._has_research_material(candidate_text):
            violations.append(
                "候选稿遗漏大纲要求的关键道具：研究资料；必须让角色带走研究资料、实验记录、数据芯片或等价载体。"
            )
        return violations

    def _with_candidate_guards(
        self,
        *,
        chapter: int,
        result: ReviewResult,
        candidate_text: str,
        reference_text: str,
        outline: dict | None,
        known_entities: list[str],
        previous_review_report: str | None = None,
    ) -> ReviewResult:
        """Add deterministic guard issues that review may miss."""
        violations = self._entity_guard_violations(
            reference_text=reference_text,
            candidate_text=candidate_text,
            outline=outline,
            known_entities=known_entities,
        )
        object_violations = self._outline_required_object_violations(
            candidate_text=candidate_text,
            outline=outline,
        )
        stale_evidence = self._stale_blocking_evidence(
            candidate_text=candidate_text,
            previous_review_report=previous_review_report or "",
        )
        if not violations and not object_violations and not stale_evidence:
            return result

        guarded = result.model_copy(deep=True)
        for violation in violations:
            guarded.issues.append(
                ReviewIssue(
                    severity="critical",
                    category="entity_guard",
                    location="全文",
                    description=violation,
                    evidence="",
                    fix_hint="必须保留大纲和既有设定中的精确实体名，不得替换为其他角色或泛称。",
                    blocking=True,
                )
            )
        for violation in object_violations:
            guarded.issues.append(
                ReviewIssue(
                    severity="critical",
                    category="outline_object_guard",
                    location="全文",
                    description=violation,
                    evidence="大纲要求“研究资料”出现在本章逃离链条中。",
                    fix_hint="必须在不改变剧情走向的前提下补入研究资料、实验记录、配方页或数据芯片等可携带载体。",
                    blocking=True,
                )
            )
        for evidence in stale_evidence:
            guarded.issues.append(
                ReviewIssue(
                    severity="critical",
                    category="stale_blocking_evidence",
                    location="旧阻断证据",
                    description="候选修复仍保留上一轮审查点名的阻断证据原文，不能判定为已修复。",
                    evidence=evidence,
                    fix_hint="必须删除、替换或补足上一轮阻断证据句，不能原样保留后直接通过。",
                    blocking=True,
                )
            )
        summary_parts: list[str] = []
        if violations:
            summary_parts.append("实体守护失败：" + "；".join(violations))
        if object_violations:
            summary_parts.append("关键道具守护失败：" + "；".join(object_violations))
        if stale_evidence:
            summary_parts.append("旧阻断证据仍保留：" + "；".join(stale_evidence[:3]))
        guarded.summary = (
            (guarded.summary + "\n" if guarded.summary else "")
            + "；".join(summary_parts)
        )
        guarded.chapter_number = chapter
        guarded.compute_derived()
        return guarded

    def _stale_blocking_evidence(
        self,
        *,
        candidate_text: str,
        previous_review_report: str,
    ) -> list[str]:
        """Return previous blocking evidence still present after a repair."""
        if not previous_review_report:
            return []

        stale: list[str] = []
        for evidence in self._blocking_evidence_texts(previous_review_report):
            if len(evidence) < 12:
                continue
            if evidence in candidate_text:
                stale.append(evidence)
        return stale

    def _is_review_engine_failure(self, result: ReviewResult) -> bool:
        return any(issue.blocking and issue.category == "review_engine" for issue in result.issues)

    def _is_repair_improvement(
        self,
        candidate: ReviewResult,
        baseline: ReviewResult,
    ) -> bool:
        """Only accept repair candidates that make review feedback smaller.

        Blocking issues are primary. For the same blocker count, a candidate can
        still be useful when it removes concrete issues; reviewers can relabel
        severity between rounds, so allow a small risk-score drift when the
        total issue list shrinks.
        """
        if candidate.passed:
            return True
        if self._is_review_engine_failure(candidate):
            return False

        candidate_score = self._review_risk_score(candidate)
        baseline_score = self._review_risk_score(baseline)

        if candidate.blocking_count < baseline.blocking_count:
            return True
        if candidate.blocking_count > baseline.blocking_count:
            return False
        if len(candidate.issues) < len(baseline.issues):
            return (
                candidate_score
                <= baseline_score + _REPAIR_SAME_BLOCKER_RISK_TOLERANCE
            )
        return (
            candidate_score < baseline_score
            and len(candidate.issues) <= len(baseline.issues)
        )

    def _review_risk_score(self, result: ReviewResult) -> int:
        """Weighted score used to decide whether a repair actually improved."""
        severity_weight = {
            "critical": 20,
            "high": 10,
            "medium": 3,
            "low": 1,
        }
        score = result.blocking_count * 1000
        for issue in result.issues:
            score += severity_weight.get(issue.severity, 3)
        return score

    def _review_metrics_label(self, result: ReviewResult) -> str:
        """Human-readable review metrics for repair logs."""
        return (
            f"阻断 {result.blocking_count} / 问题 {len(result.issues)} "
            f"/ 风险 {self._review_risk_score(result)}"
        )

    def _blocking_evidence_texts(self, review_report: str) -> list[str]:
        """Extract exact evidence quotes from blocking issue blocks."""
        texts: list[str] = []
        for block in self._blocking_report_excerpt(review_report).split("\n\n"):
            for raw in re.findall(r"^\s*-\s*\*\*证据\*\*:\s*>?\s*(.+)$", block, re.MULTILINE):
                value = raw.strip(" >\t\r\n")
                value = re.sub(r"^正文结尾[：:]\s*", "", value)
                value = re.sub(r"^原文[：:]\s*", "", value)
                value = value.strip("“”\"'")
                if 2 <= len(value) <= 220:
                    texts.append(value)

        seen: set[str] = set()
        unique: list[str] = []
        for text in texts:
            if text in seen:
                continue
            seen.add(text)
            unique.append(text)
        return unique

    def _build_micro_evidence_patch_instruction(
        self,
        *,
        evidence: str,
        review_report: str,
        outline: dict | None,
    ) -> str:
        parts = ["# 微补丁任务"]
        if outline:
            outline_lines = []
            if outline.get("summary"):
                outline_lines.append(f"- 剧情大纲: {outline['summary']}")
            if outline.get("goal"):
                outline_lines.append(f"- 本章目标: {outline['goal']}")
            if outline.get("title"):
                outline_lines.append(f"- 标题: {outline['title']}")
            parts.append("## 本章大纲\n" + "\n".join(outline_lines))
        parts.append("## 当前阻断审查报告\n" + self._blocking_report_excerpt(review_report))
        strategy_notes = self._repair_strategy_notes(review_report)
        if strategy_notes:
            parts.append(
                "## 自动诊断策略\n"
                + "\n".join(f"- {note}" for note in strategy_notes)
            )
        parts.append("## 待替换证据原文\n" + evidence)
        parts.append(
            "## 要求\n"
            "- 只替换这一个短文本。\n"
            "- new 必须解决审查指出的问题，但不能推进剧情。\n"
            "- 如果问题是错误因果或强行解释，new 必须删掉错误因果，改用正文中已经出现的道具、气味、动作或现场线索。\n"
            "- 保持周围句子可自然衔接。"
        )
        return "\n\n".join(parts)

    async def _micro_evidence_patch_repair(
        self,
        chapter_text: str,
        review_result: ReviewResult,
        review_contract: ReviewContract,
        review_report: str,
        *,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
        reference_text: str,
    ) -> tuple[str, ReviewResult, str] | None:
        """Try a surgical replacement of exact blocking evidence text."""
        if review_result.blocking_count != 1:
            return None

        for evidence in self._blocking_evidence_texts(review_report)[:3]:
            if chapter_text.count(evidence) != 1:
                continue

            instruction = self._build_micro_evidence_patch_instruction(
                evidence=evidence,
                review_report=review_report,
                outline=outline,
            )
            messages = [
                {"role": "system", "content": _MICRO_EVIDENCE_PATCH_SYSTEM_PROMPT},
                {"role": "user", "content": instruction},
            ]
            try:
                patch_data = await asyncio.wait_for(
                    self.provider.chat_json(messages, temperature=0.0, max_tokens=1024),
                    timeout=_PATCH_GENERATION_TIMEOUT,
                )
            except Exception as exc:
                warn(f"  微补丁生成失败: {exc}")
                continue

            old = str(patch_data.get("old", ""))
            new = str(patch_data.get("new", ""))
            if old != evidence or not new or old == new:
                continue

            candidate_text, applied, _ = self._apply_text_edits(
                chapter_text,
                [{"old": old, "new": new, "reason": patch_data.get("reason", "微补丁")}],
            )
            if not applied:
                continue

            candidate_result, candidate_report = await self._review_candidate_text(
                chapter=chapter,
                candidate_text=candidate_text,
                review_contract=review_contract,
                reference_text=reference_text,
                outline=outline,
                known_entities=known_entities,
                previous_review_report=review_report,
            )
            if self._is_repair_improvement(candidate_result, review_result):
                info(
                    "  已采用证据句微补丁："
                    f"{self._review_metrics_label(review_result)} -> {self._review_metrics_label(candidate_result)}。"
                )
                return candidate_text, candidate_result, candidate_report

            warn(
                "  证据句微补丁未降低风险："
                f"{self._review_metrics_label(review_result)} -> {self._review_metrics_label(candidate_result)}，已丢弃。"
            )

        return None

    def _is_chapter_overrun_report(self, review_report: str) -> bool:
        """Detect reports where a chapter consumed later outline beats."""
        return bool(
            re.search(r"(结尾|大纲|后续|提前|推进过头|越界)", review_report)
            and re.search(
                r"(后续|提前|完成|已经发生|推进|结局|下一章|后文|越界|落定)",
                review_report,
            )
        )

    def _find_tail_repair_start(self, chapter_text: str, review_report: str) -> int | None:
        """Find a suffix boundary for chapter-overrun repairs."""
        fragments = self._review_evidence_fragments(review_report)
        evidence_positions = [
            chapter_text.find(fragment)
            for fragment in fragments
            if fragment and fragment in chapter_text
        ]
        if evidence_positions:
            return min(pos for pos in evidence_positions if pos >= 0)

        paragraphs = [part for part in re.split(r"\n\s*\n", chapter_text) if part.strip()]
        if len(paragraphs) < 3:
            return None

        tail_start = max(1, int(len(paragraphs) * 0.6))
        prefix = "\n\n".join(paragraphs[:tail_start])
        return len(prefix) + 2 if prefix else None

    def _build_tail_repair_instruction(
        self,
        *,
        prefix: str,
        tail: str,
        review_report: str,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
    ) -> str:
        """Build a constrained prompt for repairing only an overrun tail."""
        parts = ["# 章节尾段修复任务"]
        if outline:
            outline_lines = [f"- 章节: 第{chapter:03d}章"]
            if outline.get("title"):
                outline_lines.append(f"- 标题: {outline['title']}")
            if outline.get("goal"):
                outline_lines.append(f"- 本章目标: {outline['goal']}")
            if outline.get("summary"):
                outline_lines.append(f"- 剧情大纲: {outline['summary']}")
            if outline.get("key_nodes"):
                outline_lines.append("- 关键节点:")
                outline_lines.extend(f"  - {item}" for item in outline["key_nodes"])
            if outline.get("ending_feeling"):
                outline_lines.append(f"- 结尾目标: {outline['ending_feeling']}")
            parts.append("## 本章大纲（必须停在这里要求的结尾）\n" + "\n".join(outline_lines))

        if known_entities:
            parts.append("## 已知实体名（必须保留精确称谓）\n" + "、".join(known_entities))

        parts.append("## 审查报告（必须修复）\n" + self._blocking_report_excerpt(review_report))
        strategy_notes = self._repair_strategy_notes(review_report)
        if strategy_notes:
            parts.append(
                "## 自动诊断修复策略\n"
                + "\n".join(f"- {note}" for note in strategy_notes)
            )

        prefix_tail = prefix[-1200:] if len(prefix) > 1200 else prefix
        parts.append("## 保留前文末尾（用于承接，不要重复输出）\n" + prefix_tail)
        parts.append("## 原尾段（需要替换）\n" + tail[:5000])
        parts.append(
            "## 修复要求\n"
            "- 只输出替换后的尾段正文。\n"
            "- 必须删除或改写提前发生的后续章节事件。\n"
            "- 尾段必须停在本章大纲指定的悬念、状态或情绪目标，不要写完后续章才该发生的结果。\n"
            "- 如果报告指出“临近/包围/逼近”和“攻破/完成/解决”混淆，必须按大纲要求保留未完成状态。\n"
            "- 如果报告指出时间、研究、手续或行动需要过程，不能让复杂结果在几分钟内直接完成。\n"
            "- 不要让关键希望、关键证据或关键人物在本章被彻底终结，除非本章大纲明确要求。"
        )
        return "\n\n".join(parts)

    async def _review_candidate_text(
        self,
        *,
        chapter: int,
        candidate_text: str,
        review_contract: ReviewContract,
        reference_text: str,
        outline: dict | None,
        known_entities: list[str],
        previous_review_report: str | None = None,
    ) -> tuple[ReviewResult, str]:
        result = await self._review_engine.review_chapter(candidate_text, review_contract)
        result = self._with_candidate_guards(
            chapter=chapter,
            result=result,
            candidate_text=candidate_text,
            reference_text=reference_text,
            outline=outline,
            known_entities=known_entities,
            previous_review_report=previous_review_report,
        )
        return result, format_review_report(result)

    async def _chapter_overrun_tail_repair(
        self,
        chapter_text: str,
        review_result: ReviewResult,
        review_contract: ReviewContract,
        review_report: str,
        *,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
        reference_text: str,
    ) -> tuple[str, ReviewResult, str] | None:
        """Repair chapter-overrun by replacing only the suffix after a safe boundary."""
        if not self._is_chapter_overrun_report(review_report):
            return None

        start = self._find_tail_repair_start(chapter_text, review_report)
        if start is None or start <= 0:
            return None

        prefix = chapter_text[:start].rstrip()
        tail = chapter_text[start:].strip()
        if not tail:
            return None

        instruction = self._build_tail_repair_instruction(
            prefix=prefix,
            tail=tail,
            review_report=review_report,
            chapter=chapter,
            outline=outline,
            known_entities=known_entities,
        )
        messages = [
            {"role": "system", "content": _TAIL_REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ]

        try:
            resp = await self.provider.chat(
                messages, temperature=0.2, max_tokens=2048
            )
        except Exception as exc:
            warn(f"  尾段越界修复失败: {exc}")
            return None

        repaired_tail = resp.content.strip()
        if not repaired_tail:
            warn("  尾段越界修复返回空内容。")
            return None

        candidate_text = prefix + "\n\n" + repaired_tail
        candidate_result, candidate_report = await self._review_candidate_text(
            chapter=chapter,
            candidate_text=candidate_text,
            review_contract=review_contract,
            reference_text=reference_text,
            outline=outline,
            known_entities=known_entities,
            previous_review_report=review_report,
        )

        if self._is_repair_improvement(candidate_result, review_result):
            info(
                "  已采用章节越界尾段修复："
                f"{self._review_metrics_label(review_result)} -> {self._review_metrics_label(candidate_result)}。"
            )
            return candidate_text, candidate_result, candidate_report

        warn(
            "  章节越界尾段修复未降低风险："
            f"{self._review_metrics_label(review_result)} -> {self._review_metrics_label(candidate_result)}，已丢弃。"
        )
        return None

    async def _generate_local_patch_edits(
        self,
        chapter_text: str,
        review_report: str,
        *,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
    ) -> list[dict]:
        """Ask the model for exact local patch proposals without applying them."""
        instruction = self._build_local_patch_instruction(
            chapter_text=chapter_text,
            review_report=review_report,
            chapter=chapter,
            outline=outline,
            known_entities=known_entities,
        )
        messages = [
            {"role": "system", "content": _LOCAL_PATCH_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ]

        try:
            patch_data = await asyncio.wait_for(
                self.provider.chat_json(messages, temperature=0.0, max_tokens=4096),
                timeout=_PATCH_GENERATION_TIMEOUT,
            )
        except Exception as exc:
            warn(f"  局部补丁生成失败: {exc}")
            return []

        edits = patch_data.get("edits", [])
        if not isinstance(edits, list) or not edits:
            warn("  未生成可应用的局部补丁。")
            return []
        return edits[:_LOCAL_PATCH_MAX_EDITS]

    async def _generate_focused_patch_edits(
        self,
        chapter_text: str,
        review_report: str,
        *,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
    ) -> list[dict]:
        """Ask for blocker-only replacements from exact risky paragraphs."""
        windows = self._focused_patch_windows(
            chapter_text,
            review_report,
            known_entities=known_entities,
        )
        if not windows:
            return []

        instruction = self._build_focused_patch_instruction(
            chapter_text=chapter_text,
            review_report=review_report,
            windows=windows,
            chapter=chapter,
            outline=outline,
            known_entities=known_entities,
        )
        messages = [
            {"role": "system", "content": _LOCAL_PATCH_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ]

        try:
            patch_data = await asyncio.wait_for(
                self.provider.chat_json(messages, temperature=0.0, max_tokens=4096),
                timeout=_PATCH_GENERATION_TIMEOUT,
            )
        except Exception as exc:
            warn(f"  聚焦阻断补丁生成失败: {exc}")
            return []

        edits = patch_data.get("edits", [])
        if not isinstance(edits, list) or not edits:
            warn("  未生成可应用的聚焦阻断补丁。")
            return []
        return edits[:_LOCAL_PATCH_MAX_EDITS]

    async def _transactional_structured_repair(
        self,
        chapter_text: str,
        review_result: ReviewResult,
        review_contract: ReviewContract,
        review_report: str,
        *,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
        reference_text: str,
    ) -> tuple[str, ReviewResult, str, int, int]:
        """Apply one LLM-planned repair task transactionally."""
        tasks = await self._generate_structured_repair_tasks(
            chapter_text,
            review_report,
            chapter=chapter,
            outline=outline,
            known_entities=known_entities,
        )
        if not tasks:
            return chapter_text, review_result, review_report, 0, 0

        rejected_count = 0
        for task in tasks[:_STRUCTURED_REPAIR_MAX_TASKS]:
            edits = await self._generate_structured_task_edits(
                chapter_text,
                task,
                outline=outline,
                known_entities=known_entities,
            )
            if not edits:
                continue

            for edit in edits[:_STRUCTURED_REPAIR_MAX_EDITS]:
                candidate_text, applied, errors = self._apply_text_edits(chapter_text, [edit])
                for item in errors:
                    logger.info("Structured repair patch skipped: %s", item)
                if not applied:
                    rejected_count += 1
                    continue

                candidate_result, candidate_report = await self._review_candidate_text(
                    chapter=chapter,
                    candidate_text=candidate_text,
                    review_contract=review_contract,
                    reference_text=reference_text,
                    outline=outline,
                    known_entities=known_entities,
                    previous_review_report=review_report,
                )
                if self._is_repair_improvement(candidate_result, review_result):
                    info(
                        "  已采用结构化修复任务 "
                        f"{task.get('issue_id', '')}: "
                        f"{self._review_metrics_label(review_result)} -> {self._review_metrics_label(candidate_result)}。"
                    )
                    return candidate_text, candidate_result, candidate_report, 1, rejected_count

                rejected_count += 1
                warn(
                    "  丢弃结构化修复任务 "
                    f"{task.get('issue_id', '')}: "
                    f"{self._review_metrics_label(review_result)} -> {self._review_metrics_label(candidate_result)}。"
                )

        return chapter_text, review_result, review_report, 0, rejected_count

    async def _transactional_local_patch_repair(
        self,
        chapter_text: str,
        review_result: ReviewResult,
        review_contract: ReviewContract,
        review_report: str,
        *,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
        reference_text: str,
    ) -> tuple[str, ReviewResult, str, int, int]:
        """Apply local patch proposals transactionally, reviewing each edit."""
        current_text = chapter_text
        current_result = review_result
        current_report = review_report
        accepted_count = 0
        rejected_count = 0

        (
            structured_text,
            structured_result,
            structured_report,
            structured_accepted,
            structured_rejected,
        ) = await self._transactional_structured_repair(
            current_text,
            current_result,
            review_contract,
            current_report,
            chapter=chapter,
            outline=outline,
            known_entities=known_entities,
            reference_text=reference_text,
        )
        rejected_count += structured_rejected
        if structured_accepted:
            return (
                structured_text,
                structured_result,
                structured_report,
                structured_accepted,
                rejected_count,
            )

        deterministic_text, deterministic_count = self._apply_deterministic_review_patches(
            current_text, current_report
        )
        if deterministic_count:
            candidate_result, candidate_report = await self._review_candidate_text(
                chapter=chapter,
                candidate_text=deterministic_text,
                review_contract=review_contract,
                reference_text=reference_text,
                outline=outline,
                known_entities=known_entities,
                previous_review_report=current_report,
            )
            if self._is_repair_improvement(candidate_result, current_result):
                current_text = deterministic_text
                current_result = candidate_result
                current_report = candidate_report
                accepted_count += deterministic_count
            else:
                rejected_count += deterministic_count
                warn(
                    f"  确定性补丁未降低风险：{self._review_metrics_label(current_result)} -> {self._review_metrics_label(candidate_result)}，已丢弃。"
                )

        edits = await self._generate_local_patch_edits(
            current_text,
            current_report,
            chapter=chapter,
            outline=outline,
            known_entities=known_entities,
        )
        local_limit = (
            _LOCAL_PATCH_SINGLE_BLOCKER_MAX_EDITS
            if current_result.blocking_count <= 1
            else _LOCAL_PATCH_MAX_EDITS
        )
        local_reject_streak = 0

        for index, edit in enumerate(edits[:local_limit], 1):
            candidate_text, applied, errors = self._apply_text_edits(current_text, [edit])
            for item in errors:
                logger.info("Transactional local patch skipped: %s", item)
            if not applied:
                rejected_count += 1
                local_reject_streak += 1
                continue

            candidate_result, candidate_report = await self._review_candidate_text(
                chapter=chapter,
                candidate_text=candidate_text,
                review_contract=review_contract,
                reference_text=reference_text,
                outline=outline,
                known_entities=known_entities,
                previous_review_report=current_report,
            )
            if self._is_repair_improvement(candidate_result, current_result):
                current_text = candidate_text
                current_result = candidate_result
                current_report = candidate_report
                accepted_count += 1
                local_reject_streak = 0
                if current_result.passed or current_result.blocking_count <= 1:
                    break
                continue

            rejected_count += 1
            local_reject_streak += 1
            warn(
                f"  丢弃局部补丁 {index}: {self._review_metrics_label(current_result)} -> {self._review_metrics_label(candidate_result)}。"
            )
            reject_limit = (
                _PATCH_REJECT_STREAK_LIMIT_SINGLE_BLOCKER
                if current_result.blocking_count <= 1
                else _PATCH_REJECT_STREAK_LIMIT
            )
            if local_reject_streak >= reject_limit:
                if current_result.blocking_count <= 1:
                    warn("  单阻断连续候选未降低风险，熔断本轮局部补丁。")
                else:
                    warn("  连续局部补丁未降低风险，提前转入下一修复策略。")
                break

        if current_result.passed:
            return current_text, current_result, current_report, accepted_count, rejected_count

        focused_edits = await self._generate_focused_patch_edits(
            current_text,
            current_report,
            chapter=chapter,
            outline=outline,
            known_entities=known_entities,
        )
        focused_limit = (
            _FOCUSED_PATCH_SINGLE_BLOCKER_MAX_EDITS
            if current_result.blocking_count <= 1
            else _FOCUSED_PATCH_MAX_EDITS
        )
        focused_reject_streak = 0
        for index, edit in enumerate(focused_edits[:focused_limit], 1):
            candidate_text, applied, errors = self._apply_text_edits(current_text, [edit])
            for item in errors:
                logger.info("Focused blocker patch skipped: %s", item)
            if not applied:
                rejected_count += 1
                focused_reject_streak += 1
                continue

            candidate_result, candidate_report = await self._review_candidate_text(
                chapter=chapter,
                candidate_text=candidate_text,
                review_contract=review_contract,
                reference_text=reference_text,
                outline=outline,
                known_entities=known_entities,
                previous_review_report=current_report,
            )
            if self._is_repair_improvement(candidate_result, current_result):
                current_text = candidate_text
                current_result = candidate_result
                current_report = candidate_report
                accepted_count += 1
                focused_reject_streak = 0
                if current_result.passed:
                    break
                continue

            rejected_count += 1
            focused_reject_streak += 1
            warn(
                f"  丢弃聚焦阻断补丁 {index}: {self._review_metrics_label(current_result)} -> {self._review_metrics_label(candidate_result)}。"
            )
            focused_reject_limit = (
                _FOCUSED_PATCH_SINGLE_BLOCKER_MAX_EDITS
                if current_result.blocking_count <= 1
                else _FOCUSED_PATCH_REJECT_STREAK_LIMIT
            )
            if focused_reject_streak >= focused_reject_limit:
                if current_result.blocking_count <= 1:
                    warn("  单阻断聚焦补丁未降低风险，停止本轮聚焦修复。")
                else:
                    warn("  聚焦阻断补丁连续无收益，停止本轮聚焦修复。")
                break

        return current_text, current_result, current_report, accepted_count, rejected_count

    async def _local_patch_repair(
        self,
        chapter_text: str,
        review_report: str,
        *,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
    ) -> tuple[str, int]:
        """Ask the model for exact local patches and apply only safe matches."""
        chapter_text, deterministic_count = self._apply_deterministic_review_patches(
            chapter_text, review_report
        )
        instruction = self._build_local_patch_instruction(
            chapter_text=chapter_text,
            review_report=review_report,
            chapter=chapter,
            outline=outline,
            known_entities=known_entities,
        )
        messages = [
            {"role": "system", "content": _LOCAL_PATCH_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ]

        try:
            patch_data = await self.provider.chat_json(
                messages, temperature=0.0, max_tokens=4096
            )
        except Exception as exc:
            warn(f"  局部补丁生成失败: {exc}")
            return chapter_text, deterministic_count

        edits = patch_data.get("edits", [])
        if not isinstance(edits, list) or not edits:
            warn("  未生成可应用的局部补丁。")
            return chapter_text, deterministic_count

        patched_text, applied_count, errors = self._apply_text_edits(chapter_text, edits)
        for item in errors:
            logger.info("Local patch skipped: %s", item)
        if errors:
            warn(f"  跳过 {len(errors)} 个不安全补丁。")
        return patched_text, applied_count + deterministic_count

    async def _repair_review_failures(
        self,
        chapter_text: str,
        review_result: ReviewResult,
        review_contract: ReviewContract,
        review_report: str,
        *,
        chapter: int,
        outline: dict | None,
        known_entities: list[str],
        review_step_message: str,
        on_step=None,
    ) -> tuple[str, ReviewResult, str]:
        """Iteratively repair review blockers using concrete review evidence."""
        base_text = chapter_text
        base_result = review_result
        base_report = review_report
        best_text = chapter_text
        best_result = review_result
        best_report = review_report

        def _step(message: str) -> None:
            info(message)
            if on_step:
                on_step(message)

        for round_index in range(1, _AUTO_REPAIR_MAX_ROUNDS + 1):
            if best_result.passed:
                break

            if round_index == 1:
                warn(
                    f"  发现 {best_result.blocking_count} 个阻断问题，按审查报告润色修复..."
                )
            else:
                warn(
                    f"  第{round_index}轮自动修复：仍有 {best_result.blocking_count} 个阻断问题，继续按最新审查报告修复..."
                )

            (
                patched_text,
                patched_result,
                patched_report,
                accepted_count,
                rejected_count,
            ) = await self._transactional_local_patch_repair(
                best_text,
                best_result,
                review_contract,
                best_report,
                chapter=chapter,
                outline=outline,
                known_entities=known_entities,
                reference_text=base_text,
            )
            if accepted_count:
                info(
                    f"  已事务提交 {accepted_count} 个局部补丁"
                    + (f"，丢弃 {rejected_count} 个风险补丁。" if rejected_count else "。")
                )
                best_text, best_result, best_report = (
                    patched_text,
                    patched_result,
                    patched_report,
                )
                if best_result.passed:
                    break
                continue
            if rejected_count:
                warn(
                    f"  本轮 {rejected_count} 个局部补丁均未降低风险，未采用。"
                )

            micro_repair = await self._micro_evidence_patch_repair(
                best_text,
                best_result,
                review_contract,
                best_report,
                chapter=chapter,
                outline=outline,
                known_entities=known_entities,
                reference_text=base_text,
            )
            if micro_repair:
                best_text, best_result, best_report = micro_repair
                if best_result.passed:
                    break
                continue

            overrun_repair = await self._chapter_overrun_tail_repair(
                best_text,
                best_result,
                review_contract,
                best_report,
                chapter=chapter,
                outline=outline,
                known_entities=known_entities,
                reference_text=base_text,
            )
            if overrun_repair:
                best_text, best_result, best_report = overrun_repair
                if best_result.passed:
                    break
                continue

            if best_result.blocking_count < _FULL_POLISH_MIN_BLOCKERS:
                warn("  剩余阻断较少，跳过全文润色以避免新增问题。")
                break

            polished_text = await self._polish(
                best_text,
                best_report,
                chapter=chapter,
                outline=outline,
                known_entities=known_entities,
            )

            _step(review_step_message)
            polished_result = await self._review_engine.review_chapter(
                polished_text, review_contract
            )
            polished_result = self._with_candidate_guards(
                chapter=chapter,
                result=polished_result,
                candidate_text=polished_text,
                reference_text=base_text,
                outline=outline,
                known_entities=known_entities,
                previous_review_report=best_report,
            )
            polished_report = format_review_report(polished_result)
            if polished_result.passed:
                best_text, best_result, best_report = (
                    polished_text,
                    polished_result,
                    polished_report,
                )
                break

            if self._is_repair_improvement(polished_result, best_result):
                best_text, best_result, best_report = (
                    polished_text,
                    polished_result,
                    polished_report,
                )
            else:
                warn(
                    f"  全文润色候选未降低风险：{self._review_metrics_label(best_result)} -> {self._review_metrics_label(polished_result)}，熔断并丢弃。"
                )
                break

        return best_text, best_result, best_report

    def _save_chapter(self, chapter: int, title: str, content: str) -> None:
        """Save chapter file to 正文/ directory."""
        path = self._paths["chapters_dir"] / chapter_filename(chapter)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = f"# {title}\n\n{content}\n"
        path.write_text(text, encoding="utf-8")
        logger.info(f"Chapter saved: {path}")

    def _save_review_report(self, chapter: int, report: str) -> None:
        """Save review report to 审查报告/ directory."""
        path = self._paths["reviews_dir"] / f"chapter_{chapter:03d}_review.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        logger.info(f"Review report saved: {path}")

    def _save_candidate(self, chapter: int, title: str, content: str, report: str) -> Path:
        """Save a rejected candidate without overwriting the official chapter."""
        candidates_dir = self._paths["aznovel_dir"] / "candidates"
        candidates_dir.mkdir(parents=True, exist_ok=True)
        chapter_path = candidates_dir / f"chapter_{chapter:03d}.candidate.md"
        review_path = candidates_dir / f"chapter_{chapter:03d}.candidate_review.md"
        chapter_path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        review_path.write_text(report, encoding="utf-8")
        logger.info("Candidate saved: %s", chapter_path)
        return chapter_path

    def _clear_candidate(self, chapter: int) -> None:
        """Remove stale rejected-candidate files after an official save."""
        candidates_dir = self._paths["aznovel_dir"] / "candidates"
        for suffix in (".candidate.md", ".candidate_review.md"):
            path = candidates_dir / f"chapter_{chapter:03d}{suffix}"
            if path.exists():
                path.unlink()
                logger.info("Candidate cleared: %s", path)

    def _split_chapter_document(self, raw: str, chapter: int) -> tuple[str, str]:
        """Split a saved chapter Markdown document into title and body."""
        lines = raw.split("\n")
        if lines and lines[0].startswith("# "):
            title = lines[0].lstrip("#").strip() or f"第{chapter}章"
            body = "\n".join(lines[1:]).strip()
            return title, body
        return f"第{chapter}章", raw.strip()

    def _load_chapter_documents(self) -> dict[int, dict[str, str | Path]]:
        """Load all saved chapter documents, preserving their titles and paths."""
        chapters_dir = self._paths["chapters_dir"]
        if not chapters_dir.exists():
            return {}

        documents: dict[int, dict[str, str | Path]] = {}
        for path in sorted(chapters_dir.glob("第*章.md")):
            chapter = extract_chapter_number(path.name)
            if not chapter:
                continue
            raw = path.read_text(encoding="utf-8")
            title, body = self._split_chapter_document(raw, chapter)
            documents[chapter] = {
                "path": path,
                "raw": raw,
                "title": title,
                "body": body,
            }
        return documents

    def _detect_final_safe_issues(self, chapter_texts: dict[int, str]) -> list[dict]:
        """Detect cross-chapter hard-logic issues that saved review reports may miss.

        Each issue carries exact old/new edits. The repair step only applies these
        snippets when they are unique in the target chapter; otherwise it refuses
        the patch and leaves the official manuscript untouched.
        """
        issues: list[dict] = []

        def add_issue(
            issue_id: str,
            chapter: int,
            description: str,
            evidence: list[str],
            edits: list[dict],
        ) -> None:
            issues.append(
                {
                    "id": issue_id,
                    "chapter": chapter,
                    "description": description,
                    "evidence": evidence,
                    "edits": edits,
                }
            )

        ch3 = chapter_texts.get(3, "")
        ch4 = chapter_texts.get(4, "")
        ch5 = chapter_texts.get(5, "")
        ch6 = chapter_texts.get(6, "")
        ch8 = chapter_texts.get(8, "")
        ch9 = chapter_texts.get(9, "")
        ch10 = chapter_texts.get(10, "")

        if (
            "掌心的纹路里，有一抹洗不掉的淡绿色" in ch3
            and "微弱的荧光已经蔓延到了手腕" in ch4
            and "手背上的青紫斑块似乎比刚才更鲜艳了一些" in ch5
            and "那里只有粗糙的皮肤和紧绷的肌肉" in ch6
        ):
            old = (
                "周也的手指悬在旋钮上，指节因用力而泛白。赵德柱在监控画面里变成青紫色人形茧的场景像烙铁一样印在视网膜上，"
                "他下意识地摩挲着自己的小臂，那里只有粗糙的皮肤和紧绷的肌肉。他绝不能让那场异变在儿子身上重演。"
            )
            new = (
                "周也的手指悬在旋钮上，指节因用力而泛白。赵德柱在监控画面里变成青紫色人形茧的场景像烙铁一样印在视网膜上，"
                "他下意识地摩挲着自己的小臂，掌纹里那抹淡绿在皮下若隐若现，只是没有像儿子那样凸起、游走。"
                "他绝不能让那场异变在儿子身上重演。"
            )
            add_issue(
                "C06_ZHOU_INFECTION_CONTINUITY",
                6,
                "周也第3-5章已有手部感染线索，第6章却写成小臂完全正常。",
                [
                    "第3章：掌心淡绿色隐隐发光",
                    "第4章：荧光蔓延到手腕",
                    "第5章：手背青紫斑块更鲜艳",
                    "第6章：那里只有粗糙的皮肤和紧绷的肌肉",
                ],
                [{"old": old, "new": new, "reason": "保留周也自身感染线索，同时区分于儿子的重度异变"}],
            )

        if "1.0阶段遇到的排异反应不是bug" in ch4 and "“禾苗1.0是安全的。”" in ch8:
            old = "“禾苗1.0是安全的。”汪禾的视线落在试管上，像在看一个被谋杀的孩子，"
            new = "“禾苗1.0在我的模型里本该是安全的。”汪禾的视线落在试管上，像在看一个被谋杀的孩子，"
            add_issue(
                "C08_HM10_ABSOLUTE_SAFETY_TENSION",
                8,
                "第4章已承认1.0存在排异反应，第8章不应再绝对宣称1.0安全。",
                ["第4章：1.0阶段遇到排异反应", "第8章：禾苗1.0是安全的"],
                [{"old": old, "new": new, "reason": "把绝对安全改成汪禾模型中的预期，兼容早期排异线索"}],
            )

        if "装着逆转录酶的空试管" in ch8 and "里面透明的液体是周小禾仅存的概率" in ch9:
            old = "一根纤细的藤蔓从操作台边缘探出头来，像一条吐信的毒蛇，缓缓伸向了那支装着逆转录酶的空试管。"
            new = "一根纤细的藤蔓从操作台边缘探出头来，像一条吐信的毒蛇，缓缓伸向了那支装着逆转录酶的试管。"
            add_issue(
                "C08_RT_TUBE_EMPTY_CONFLICT",
                8,
                "第8章把装着逆转录酶的试管写成空试管，第9章开头又明确里面有透明液体。",
                ["第8章：装着逆转录酶的空试管", "第9章：里面透明的液体"],
                [{"old": old, "new": new, "reason": "删除“空”字，保持试管状态与第9章一致"}],
            )

        if (
            "汪禾塞进来的防水资料袋" in ch9
            and "又把一只防水资料袋压在试管旁边" not in ch9
            and "汪禾没有将试管递给他，而是猛地将其塞进了周也胸前的急救包" in ch9
        ):
            old = (
                "汪禾的手指搭上了那管逆转录酶。周也的肌肉瞬间绷紧，但汪禾没有将试管递给他，"
                "而是猛地将其塞进了周也胸前的急救包，拉链拉上的声音在嘈杂中异常刺耳。"
            )
            new = (
                "汪禾的手指搭上了那管逆转录酶。周也的肌肉瞬间绷紧，但汪禾没有将试管递给他，"
                "而是猛地将其塞进了周也胸前的急救包，又把一只防水资料袋压在试管旁边，拉链拉上的声音在嘈杂中异常刺耳。"
            )
            add_issue(
                "C09_RESEARCH_BAG_SETUP_MISSING",
                9,
                "第9章后文出现防水资料袋，但汪禾交付试管时没有交付资料袋动作。",
                ["第9章前段：只写塞入逆转录酶", "第9章后段：急救包里的防水资料袋"],
                [{"old": old, "new": new, "reason": "补足资料袋进入急救包的动作，避免物品凭空出现"}],
            )

        if "逆转录酶没有起效" in ch10 and "酶还在，但他并没有给周小禾使用" in ch9:
            old = "实验室里的奇迹并未发生，逆转录酶没有起效。"
            new = "实验室里的奇迹并未发生，逆转录酶还躺在急救包里，没有催化剂，也没有时间变成真正的解药。"
            add_issue(
                "C10_RT_NOT_USED_BUT_FAILED",
                10,
                "第9章明确逆转录酶没有使用，第10章却写成逆转录酶已经使用但未起效。",
                ["第9章：酶还在，但并没有给周小禾使用", "第10章：逆转录酶没有起效"],
                [{"old": old, "new": new, "reason": "改为未完成解药，而不是已使用失败"}],
            )

        if "这是汪禾用命换来的，是此刻方圆百里内唯一能让他们迅速“长肉”的东西。" in ch10:
            old = "这是汪禾用命换来的，是此刻方圆百里内唯一能让他们迅速“长肉”的东西。"
            new = "这是周也留下的最后一点保命糖分，却也是此刻方圆百里内唯一能让他们迅速“长肉”的东西。"
            add_issue(
                "C10_GLUCOSE_GEL_SOURCE_CONFLICT",
                10,
                "第9章葡萄糖凝胶是周也自己的最后储备，第10章误写成汪禾用命换来。",
                ["第9章：周也原本打算留作最后保命用的葡萄糖凝胶", "第10章：这是汪禾用命换来的"],
                [{"old": old, "new": new, "reason": "统一葡萄糖凝胶来源"}],
            )

        if "精准定位" in ch10 or "精准收割" in ch10:
            edits = []
            if "藤蔓会循着养分的浓度精准定位" in ch10:
                edits.append(
                    {
                        "old": "藤蔓会循着养分的浓度精准定位",
                        "new": "藤蔓会循着养分浓度找来",
                        "reason": "把工程化术语收回到可感知的生物趋化行为",
                    }
                )
            if "引导藤蔓精准收割" in ch10:
                edits.append(
                    {
                        "old": "引导藤蔓精准收割",
                        "new": "引导藤蔓循着标记收割",
                        "reason": "避免把前财务主角的认知写成军事化精准战术表述",
                    }
                )
            if edits:
                add_issue(
                    "C10_TERMINOLOGY_ACCOUNTANT_OOC",
                    10,
                    "第10章局部术语偏工程/军事化，削弱周也前财务视角的可信度。",
                    ["第10章：精准定位/精准收割"],
                    edits,
                )

        if "“爸……”周小禾喘息着，声音微弱得几乎听不见，“我是不是要死了？”" in ch10:
            edits = [
                {
                    "old": "“爸……”周小禾喘息着，声音微弱得几乎听不见，“我是不是要死了？”",
                    "new": "“爸……”周小禾喘息着，声音微弱得几乎听不见，“我们会死吗？”",
                    "reason": "贴合结尾父子共同困境，也对齐大纲指定问句",
                }
            ]
            if "“不会。”周也把手从兜里抽出来，没有带出凝胶。" in ch10:
                edits.append(
                    {
                        "old": "“不会。”周也把手从兜里抽出来，没有带出凝胶。",
                        "new": "“我不知道。”周也把手从兜里抽出来，没有带出凝胶。",
                        "reason": "避免虚假保证，承接后文“我会一直带你走下去”的答案",
                    }
                )
            add_issue(
                "C10_ENDING_DIALOGUE_ALIGNMENT",
                10,
                "第10章结尾问答与大纲指定的“我们会死吗/我不知道，但会一直带你走”存在偏差。",
                ["第10章：我是不是要死了/不会", "大纲结尾：我们会死吗/我不知道/一直带你走"],
                edits,
            )

        return issues

    def _validate_final_safe_repair(
        self,
        original_texts: dict[int, str],
        candidate_texts: dict[int, str],
        issues: list[dict],
    ) -> list[str]:
        """Validate that final safe repair stayed small and resolved targeted issues."""
        errors: list[str] = []

        for issue in issues:
            chapter = int(issue["chapter"])
            before = original_texts.get(chapter, "")
            after = candidate_texts.get(chapter, "")
            if not before or not after:
                errors.append(f"{issue['id']}: 第{chapter:03d}章正文缺失")
                continue
            if before == after:
                errors.append(f"{issue['id']}: 第{chapter:03d}章没有发生变化")
                continue

            delta = abs(len(after) - len(before))
            limit = max(
                _FINAL_SAFE_REPAIR_MAX_CHANGE_CHARS,
                int(len(before) * _FINAL_SAFE_REPAIR_MAX_CHANGE_RATIO),
            )
            if delta > limit:
                errors.append(
                    f"{issue['id']}: 第{chapter:03d}章改动过大 ({delta} 字符 > {limit})"
                )

            for edit in issue.get("edits", []):
                old = str(edit.get("old", ""))
                new = str(edit.get("new", ""))
                if old and old in after:
                    errors.append(f"{issue['id']}: old 文本仍然存在")
                if new and new not in after:
                    errors.append(f"{issue['id']}: new 文本未出现在候选稿")

        selected_ids = {issue["id"] for issue in issues}

        if "C06_ZHOU_INFECTION_CONTINUITY" in selected_ids:
            ch6 = candidate_texts.get(6, "")
            if "那里只有粗糙的皮肤和紧绷的肌肉" in ch6:
                errors.append("C06_ZHOU_INFECTION_CONTINUITY: 第6章仍否认周也感染线索")
            if "掌纹里那抹淡绿" not in ch6:
                errors.append("C06_ZHOU_INFECTION_CONTINUITY: 第6章未保留周也淡绿感染线索")

        if "C08_HM10_ABSOLUTE_SAFETY_TENSION" in selected_ids:
            ch8 = candidate_texts.get(8, "")
            if "“禾苗1.0是安全的。”" in ch8:
                errors.append("C08_HM10_ABSOLUTE_SAFETY_TENSION: 第8章仍绝对宣称1.0安全")

        if "C08_RT_TUBE_EMPTY_CONFLICT" in selected_ids:
            ch8 = candidate_texts.get(8, "")
            if "装着逆转录酶的空试管" in ch8:
                errors.append("C08_RT_TUBE_EMPTY_CONFLICT: 第8章仍保留逆转录酶空试管")

        if "C09_RESEARCH_BAG_SETUP_MISSING" in selected_ids:
            ch9 = candidate_texts.get(9, "")
            if "又把一只防水资料袋压在试管旁边" not in ch9:
                errors.append("C09_RESEARCH_BAG_SETUP_MISSING: 第9章未补足资料袋交付动作")

        if "C10_RT_NOT_USED_BUT_FAILED" in selected_ids:
            ch10 = candidate_texts.get(10, "")
            if "逆转录酶没有起效" in ch10:
                errors.append("C10_RT_NOT_USED_BUT_FAILED: 第10章仍写成逆转录酶未起效")

        if "C10_GLUCOSE_GEL_SOURCE_CONFLICT" in selected_ids:
            ch10 = candidate_texts.get(10, "")
            if "这是汪禾用命换来的，是此刻方圆百里内唯一能让他们迅速“长肉”的东西。" in ch10:
                errors.append("C10_GLUCOSE_GEL_SOURCE_CONFLICT: 第10章仍误写葡萄糖凝胶来源")

        if "C10_TERMINOLOGY_ACCOUNTANT_OOC" in selected_ids:
            ch10 = candidate_texts.get(10, "")
            if "精准定位" in ch10 or "精准收割" in ch10:
                errors.append("C10_TERMINOLOGY_ACCOUNTANT_OOC: 第10章仍保留精准定位/精准收割")

        if "C10_ENDING_DIALOGUE_ALIGNMENT" in selected_ids:
            ch10 = candidate_texts.get(10, "")
            if "我们会死吗" not in ch10 or "“我不知道。”" not in ch10:
                errors.append("C10_ENDING_DIALOGUE_ALIGNMENT: 第10章结尾问答未对齐")

        return errors

    def _detect_final_polish_issues(self, chapter_texts: dict[int, str]) -> list[dict]:
        """Detect small final-polish issues after safety repair has passed.

        This pass is intentionally narrow: it only touches wording that is visibly
        out of manuscript voice, tiny bridge gaps, or local phrasing that survived
        the structural repair pass.
        """
        issues: list[dict] = []

        def add_issue(
            issue_id: str,
            chapter: int,
            description: str,
            evidence: list[str],
            edits: list[dict],
        ) -> None:
            issues.append(
                {
                    "id": issue_id,
                    "chapter": chapter,
                    "description": description,
                    "evidence": evidence,
                    "edits": edits,
                }
            )

        ch7 = chapter_texts.get(7, "")
        ch8 = chapter_texts.get(8, "")
        ch10 = chapter_texts.get(10, "")

        if "而卡路里必须数量闭环" in ch7:
            old = (
                "周也没有接话，他拉起儿子，沿着水渠继续往远离城区的方向走。"
                "荒野求生不是电影里的浪漫，每一寸推进都在消耗卡路里，而卡路里必须数量闭环。"
                "半块饼干撑不过今晚，他必须找到食物，或者至少，找到一个能避开夜间追捕的掩体。"
            )
            new = (
                "周也没有接话，他拉起儿子，沿着水渠继续往远离城区的方向走。"
                "荒野求生不是电影里的浪漫，每一寸推进都在消耗卡路里，每一点热量都得从牙缝里抠出来。"
                "半块饼干撑不过今晚，他必须找到食物，或者至少，找到一个能避开夜间追捕的掩体。"
            )
            add_issue(
                "C07_REMOVE_REVIEW_JARGON",
                7,
                "第7章残留“数量闭环”这类流程/审查术语，破坏正文沉浸感。",
                ["第7章：卡路里必须数量闭环"],
                [{"old": old, "new": new, "reason": "删除流程术语，改成角色视角中的饥饿计算"}],
            )

        if (
            "这里是那个男人临死前提及的地方——植物生态研究所的地下核心区" in ch8
            and "不管是死是活，汪禾都不会再出现了。我们没救了。" in ch7
        ):
            old = (
                "“什么都没有。”男人痛苦地抓挠着头皮，“连张纸片都没留下。"
                "他是个疯子，他以为自己在创造神，结果造出了魔鬼，最后只能选择消失。"
                "不管是死是活，汪禾都不会再出现了。我们没救了。”"
            )
            new = (
                "“只有一个旧地址。”男人痛苦地抓挠着头皮，“植物生态研究所地下核心区，没坐标，没通行码，连张纸片都没留下。"
                "他是个疯子，他以为自己在创造神，结果造出了魔鬼，最后只能选择消失。"
                "就算他活着，也没人能把他从地下翻出来。我们没救了。”"
            )
            follow_old = (
                "绝望像冰冷的蛇，顺着周也的脊椎爬上来。他看着男人空洞的眼睛，知道那不是谎言。"
                "寻找源头的希望被生生掐断，只剩下一地灰烬。"
            )
            follow_new = (
                "绝望像冰冷的蛇，顺着周也的脊椎爬上来。他看着男人空洞的眼睛，知道那不是谎言。"
                "所谓旧地址更像一枚丢进黑暗里的钉子，能不能摸到，全看命。"
            )
            add_issue(
                "C07_C08_BRIDGE_THIN",
                7,
                "第8章开头已到研究所地下核心区，第7章临终线索过桥偏薄。",
                ["第7章：汪禾不会再出现/什么都没有", "第8章：那个男人临死前提及的地方"],
                [
                    {"old": old, "new": new, "reason": "给第8章研究所入口补足一句可追踪的旧地址线索"},
                    {"old": follow_old, "new": follow_new, "reason": "把绝望判断改成冒险线索，不和第8章抵触"},
                ],
            )

        if "手里的空试管" in ch8 and "里面残留着几滴浑浊的液体" in ch8:
            old = "汪禾沉默了。他低头看着手里的空试管，手指不受控制地摩挲着玻璃壁。"
            new = "汪禾沉默了。他低头看着手里的残液试管，手指不受控制地摩挲着玻璃壁。"
            add_issue(
                "C08_RESIDUE_TUBE_WORDING",
                8,
                "第8章同一支试管先有残液后称空试管，虽非逆转录酶试管但读感不稳。",
                ["第8章：里面残留几滴浑浊液体", "第8章：手里的空试管"],
                [{"old": old, "new": new, "reason": "统一试管状态，避免读者误判为新矛盾"}],
            )

        if "这颗星球已经变成了一个巨大的餐盘" in ch10:
            old = (
                "没有安全的地方。这颗星球已经变成了一个巨大的餐盘。"
                "他们能做的，只是做一道难以下咽的菜，在餐盘的边缘不断游走，躲避着刀叉的叉取。"
            )
            new = (
                "没有安全的地方。整座城市都在同一张食物链里翻面，"
                "他们能做的，只是让自己始终难以下咽，在绿色边缘一点点挪开。"
            )
            add_issue(
                "C10_SOFTEN_OVERWRITTEN_METAPHOR",
                10,
                "第10章结尾“巨大餐盘/刀叉”比喻略显直白，削弱末尾冷峻感。",
                ["第10章：巨大餐盘/刀叉的叉取"],
                [{"old": old, "new": new, "reason": "收敛比喻，让结尾保持冷峻克制"}],
            )

        return issues

    def _validate_final_polish(
        self,
        original_texts: dict[int, str],
        candidate_texts: dict[int, str],
        issues: list[dict],
    ) -> list[str]:
        """Validate that final polish stays small and removes targeted rough spots."""
        errors: list[str] = []
        for issue in issues:
            chapter = int(issue["chapter"])
            before = original_texts.get(chapter, "")
            after = candidate_texts.get(chapter, "")
            if not before or not after:
                errors.append(f"{issue['id']}: 第{chapter:03d}章正文缺失")
                continue
            if before == after:
                errors.append(f"{issue['id']}: 第{chapter:03d}章没有发生变化")
                continue

            delta = abs(len(after) - len(before))
            limit = max(
                _FINAL_SAFE_REPAIR_MAX_CHANGE_CHARS,
                int(len(before) * _FINAL_SAFE_REPAIR_MAX_CHANGE_RATIO),
            )
            if delta > limit:
                errors.append(
                    f"{issue['id']}: 第{chapter:03d}章改动过大 ({delta} 字符 > {limit})"
                )

            for edit in issue.get("edits", []):
                old = str(edit.get("old", ""))
                new = str(edit.get("new", ""))
                if old and old in after:
                    errors.append(f"{issue['id']}: old 文本仍然存在")
                if new and new not in after:
                    errors.append(f"{issue['id']}: new 文本未出现在候选稿")

        selected_ids = {issue["id"] for issue in issues}
        if "C07_REMOVE_REVIEW_JARGON" in selected_ids and "数量闭环" in candidate_texts.get(7, ""):
            errors.append("C07_REMOVE_REVIEW_JARGON: 第7章仍残留数量闭环")
        if "C07_C08_BRIDGE_THIN" in selected_ids and "植物生态研究所地下核心区" not in candidate_texts.get(7, ""):
            errors.append("C07_C08_BRIDGE_THIN: 第7章未补足研究所地下核心区线索")
        if "C08_RESIDUE_TUBE_WORDING" in selected_ids and "手里的空试管" in candidate_texts.get(8, ""):
            errors.append("C08_RESIDUE_TUBE_WORDING: 第8章仍保留手里的空试管")
        if "C10_SOFTEN_OVERWRITTEN_METAPHOR" in selected_ids and "巨大的餐盘" in candidate_texts.get(10, ""):
            errors.append("C10_SOFTEN_OVERWRITTEN_METAPHOR: 第10章仍保留巨大餐盘比喻")
        return errors

    def _write_final_polish_report(
        self,
        session_dir: Path,
        *,
        issues: list[dict],
        changed_chapters: list[int],
        apply_errors: list[str],
        validation_errors: list[str],
        dry_run: bool,
    ) -> Path:
        """Persist a concise final-polish report."""
        lines = ["# 终稿精修报告", ""]
        lines.append(f"- 模式: {'演练（未覆盖正文）' if dry_run else '正式精修'}")
        lines.append(f"- 发现问题: {len(issues)}")
        lines.append(
            "- 修改章节: "
            + (", ".join(f"第{chapter:03d}章" for chapter in changed_chapters) or "无")
        )
        lines.append("")

        if issues:
            lines.append("## 问题与补丁")
            for issue in issues:
                lines.append(f"### {issue['id']} / 第{int(issue['chapter']):03d}章")
                lines.append(issue["description"])
                if issue.get("evidence"):
                    lines.append("")
                    lines.append("证据:")
                    lines.extend(f"- {item}" for item in issue["evidence"])
                if issue.get("edits"):
                    lines.append("")
                    lines.append("补丁:")
                    for edit in issue["edits"]:
                        lines.append(f"- {edit.get('reason', '').strip()}")
                lines.append("")

        if apply_errors:
            lines.append("## 应用失败")
            lines.extend(f"- {item}" for item in apply_errors)
            lines.append("")

        if validation_errors:
            lines.append("## 校验失败")
            lines.extend(f"- {item}" for item in validation_errors)
            lines.append("")
        else:
            lines.append("## 校验结果")
            lines.append("全部精修补丁通过 exact old/new 与残留校验。")
            lines.append("")

        report = "\n".join(lines)
        session_dir.mkdir(parents=True, exist_ok=True)
        report_path = session_dir / "report.md"
        report_path.write_text(report, encoding="utf-8")

        latest_path = self._paths["aznovel_dir"] / "final_polish" / "latest_report.md"
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        latest_path.write_text(report, encoding="utf-8")
        return report_path

    def _write_final_safe_repair_report(
        self,
        session_dir: Path,
        *,
        issues: list[dict],
        changed_chapters: list[int],
        apply_errors: list[str],
        validation_errors: list[str],
        dry_run: bool,
    ) -> Path:
        """Persist a concise final-safe-repair audit report."""
        lines = ["# 最终安全修复报告", ""]
        lines.append(f"- 模式: {'演练（未覆盖正文）' if dry_run else '正式修复'}")
        lines.append(f"- 发现问题: {len(issues)}")
        lines.append(
            "- 修改章节: "
            + (", ".join(f"第{chapter:03d}章" for chapter in changed_chapters) or "无")
        )
        lines.append("")

        if issues:
            lines.append("## 问题与补丁")
            for issue in issues:
                lines.append(f"### {issue['id']} / 第{int(issue['chapter']):03d}章")
                lines.append(issue["description"])
                if issue.get("evidence"):
                    lines.append("")
                    lines.append("证据:")
                    lines.extend(f"- {item}" for item in issue["evidence"])
                if issue.get("edits"):
                    lines.append("")
                    lines.append("补丁:")
                    for edit in issue["edits"]:
                        lines.append(f"- {edit.get('reason', '').strip()}")
                lines.append("")

        if apply_errors:
            lines.append("## 应用失败")
            lines.extend(f"- {item}" for item in apply_errors)
            lines.append("")

        if validation_errors:
            lines.append("## 校验失败")
            lines.extend(f"- {item}" for item in validation_errors)
            lines.append("")
        else:
            lines.append("## 校验结果")
            lines.append("全部补丁通过 exact old/new 与硬逻辑残留校验。")
            lines.append("")

        report = "\n".join(lines)
        session_dir.mkdir(parents=True, exist_ok=True)
        report_path = session_dir / "report.md"
        report_path.write_text(report, encoding="utf-8")

        latest_path = self._paths["aznovel_dir"] / "final_safe_repair" / "latest_report.md"
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        latest_path.write_text(report, encoding="utf-8")
        return report_path

    async def final_safe_repair(
        self,
        *,
        chapters: list[int] | None = None,
        dry_run: bool = False,
        on_step=None,
    ) -> bool:
        """Run cross-chapter final safety repair with exact small patches only."""
        def _step(msg: str):
            info(msg)
            if on_step:
                on_step(msg)

        _step("最终安全终检：读取正文...")
        documents = self._load_chapter_documents()
        if not documents:
            error("还没有任何正式章节，无法执行最终安全修复。")
            return False

        selected_chapters = set(int(ch) for ch in chapters) if chapters else None
        chapter_texts = {
            chapter: str(doc["body"])
            for chapter, doc in documents.items()
        }
        issues = self._detect_final_safe_issues(chapter_texts)
        if selected_chapters is not None:
            issues = [
                issue for issue in issues
                if int(issue["chapter"]) in selected_chapters
            ]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self._paths["aznovel_dir"] / "final_safe_repair" / timestamp

        if not issues:
            self._write_final_safe_repair_report(
                session_dir,
                issues=[],
                changed_chapters=[],
                apply_errors=[],
                validation_errors=[],
                dry_run=dry_run,
            )
            success("最终安全终检完成：未发现可安全修复的硬逻辑问题。")
            return True

        _step(f"最终安全修复：发现 {len(issues)} 个硬逻辑问题，生成小补丁...")
        original_texts = dict(chapter_texts)
        candidate_texts = dict(chapter_texts)
        apply_errors: list[str] = []
        applied_by_chapter: dict[int, int] = {}

        for chapter in sorted({int(issue["chapter"]) for issue in issues}):
            edits: list[dict] = []
            for issue in issues:
                if int(issue["chapter"]) == chapter:
                    edits.extend(issue.get("edits", []))

            candidate, applied, errors = self._apply_text_edits(
                candidate_texts[chapter],
                edits,
            )
            candidate_texts[chapter] = candidate
            if applied:
                applied_by_chapter[chapter] = applied
            apply_errors.extend(f"第{chapter:03d}章: {item}" for item in errors)

        changed_chapters = [
            chapter for chapter, text in candidate_texts.items()
            if text != original_texts.get(chapter)
        ]
        validation_errors = self._validate_final_safe_repair(
            original_texts,
            candidate_texts,
            issues,
        )
        if apply_errors:
            validation_errors.extend(apply_errors)

        report_path = self._write_final_safe_repair_report(
            session_dir,
            issues=issues,
            changed_chapters=sorted(changed_chapters),
            apply_errors=apply_errors,
            validation_errors=validation_errors,
            dry_run=dry_run,
        )

        if validation_errors:
            warn(f"最终安全修复未通过校验，正式正文未覆盖。报告: {report_path}")
            for item in validation_errors[:8]:
                warn(f"  - {item}")
            return False

        after_dir = session_dir / "after"
        before_dir = session_dir / "before"
        before_dir.mkdir(parents=True, exist_ok=True)
        after_dir.mkdir(parents=True, exist_ok=True)

        for chapter in sorted(changed_chapters):
            doc = documents[chapter]
            path = doc["path"]
            assert isinstance(path, Path)
            title = str(doc["title"])
            before_dir.joinpath(path.name).write_text(str(doc["raw"]), encoding="utf-8")
            after_dir.joinpath(path.name).write_text(
                f"# {title}\n\n{candidate_texts[chapter]}\n",
                encoding="utf-8",
            )

        if dry_run:
            success(
                f"最终安全修复演练完成：{len(issues)} 个问题、{len(changed_chapters)} 章可修复。报告: {report_path}"
            )
            return True

        _step("最终安全修复：备份并覆盖通过校验的章节...")
        for chapter in sorted(changed_chapters):
            doc = documents[chapter]
            self._save_chapter(chapter, str(doc["title"]), candidate_texts[chapter])

        total_edits = sum(applied_by_chapter.values())
        success(
            f"最终安全修复完成：修复 {len(issues)} 个问题，应用 {total_edits} 个小补丁，修改 {len(changed_chapters)} 章。"
        )
        info(f"修复报告: {report_path}")
        return True

    async def final_polish(
        self,
        *,
        chapters: list[int] | None = None,
        dry_run: bool = False,
        on_step=None,
    ) -> bool:
        """Run final manuscript polish with exact small patches only."""
        def _step(msg: str):
            info(msg)
            if on_step:
                on_step(msg)

        _step("终稿精修：读取正文...")
        documents = self._load_chapter_documents()
        if not documents:
            error("还没有任何正式章节，无法执行终稿精修。")
            return False

        selected_chapters = set(int(ch) for ch in chapters) if chapters else None
        chapter_texts = {
            chapter: str(doc["body"])
            for chapter, doc in documents.items()
        }
        issues = self._detect_final_polish_issues(chapter_texts)
        if selected_chapters is not None:
            issues = [
                issue for issue in issues
                if int(issue["chapter"]) in selected_chapters
            ]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self._paths["aznovel_dir"] / "final_polish" / timestamp

        if not issues:
            self._write_final_polish_report(
                session_dir,
                issues=[],
                changed_chapters=[],
                apply_errors=[],
                validation_errors=[],
                dry_run=dry_run,
            )
            success("终稿精修完成：未发现可安全精修的正文问题。")
            return True

        _step(f"终稿精修：发现 {len(issues)} 个小问题，生成小补丁...")
        original_texts = dict(chapter_texts)
        candidate_texts = dict(chapter_texts)
        apply_errors: list[str] = []
        applied_by_chapter: dict[int, int] = {}

        for chapter in sorted({int(issue["chapter"]) for issue in issues}):
            edits: list[dict] = []
            for issue in issues:
                if int(issue["chapter"]) == chapter:
                    edits.extend(issue.get("edits", []))

            candidate, applied, errors = self._apply_text_edits(
                candidate_texts[chapter],
                edits,
            )
            candidate_texts[chapter] = candidate
            if applied:
                applied_by_chapter[chapter] = applied
            apply_errors.extend(f"第{chapter:03d}章: {item}" for item in errors)

        changed_chapters = [
            chapter for chapter, text in candidate_texts.items()
            if text != original_texts.get(chapter)
        ]
        validation_errors = self._validate_final_polish(
            original_texts,
            candidate_texts,
            issues,
        )
        if apply_errors:
            validation_errors.extend(apply_errors)

        report_path = self._write_final_polish_report(
            session_dir,
            issues=issues,
            changed_chapters=sorted(changed_chapters),
            apply_errors=apply_errors,
            validation_errors=validation_errors,
            dry_run=dry_run,
        )

        if validation_errors:
            warn(f"终稿精修未通过校验，正式正文未覆盖。报告: {report_path}")
            for item in validation_errors[:8]:
                warn(f"  - {item}")
            return False

        after_dir = session_dir / "after"
        before_dir = session_dir / "before"
        before_dir.mkdir(parents=True, exist_ok=True)
        after_dir.mkdir(parents=True, exist_ok=True)

        for chapter in sorted(changed_chapters):
            doc = documents[chapter]
            path = doc["path"]
            assert isinstance(path, Path)
            title = str(doc["title"])
            before_dir.joinpath(path.name).write_text(str(doc["raw"]), encoding="utf-8")
            after_dir.joinpath(path.name).write_text(
                f"# {title}\n\n{candidate_texts[chapter]}\n",
                encoding="utf-8",
            )

        if dry_run:
            success(
                f"终稿精修演练完成：{len(issues)} 个问题、{len(changed_chapters)} 章可精修。报告: {report_path}"
            )
            return True

        _step("终稿精修：备份并覆盖通过校验的章节...")
        for chapter in sorted(changed_chapters):
            doc = documents[chapter]
            self._save_chapter(chapter, str(doc["title"]), candidate_texts[chapter])

        total_edits = sum(applied_by_chapter.values())
        success(
            f"终稿精修完成：修复 {len(issues)} 个小问题，应用 {total_edits} 个小补丁，修改 {len(changed_chapters)} 章。"
        )
        info(f"精修报告: {report_path}")
        return True

    async def auto_run_book(
        self,
        *,
        target: int | None = None,
        max_repair_attempts: int = AUTO_RUN_REPAIR_ATTEMPTS_DEFAULT,
        on_step=None,
    ) -> bool:
        """Write missing chapters through normal review, then finalize the manuscript."""
        def _step(msg: str):
            info(msg)
            if on_step:
                on_step(msg)

        state = self._state_store.load()
        if not state.project_info.title:
            error("项目未初始化。请先运行 'aznovel init'")
            return False

        if target is None:
            target = state.project_info.target_chapters
        try:
            target = int(target)
        except (TypeError, ValueError):
            error("无人值守写作需要有效的目标章数。")
            return False
        if target <= 0:
            error("无人值守写作的目标章数必须大于 0。")
            return False

        try:
            max_repair_attempts = int(max_repair_attempts)
        except (TypeError, ValueError):
            max_repair_attempts = AUTO_RUN_REPAIR_ATTEMPTS_DEFAULT
        max_repair_attempts = max(0, max_repair_attempts)

        chapters_dir = self._paths["chapters_dir"]
        chapters_dir.mkdir(parents=True, exist_ok=True)
        existing_numbers = sorted(
            num
            for path in chapters_dir.glob("第*章.md")
            for num in [extract_chapter_number(path.name)]
            if num is not None
        )
        if existing_numbers and max(existing_numbers) > target:
            warn(
                f"已有正式正文最高到第{max(existing_numbers):03d}章，超过目标第{target:03d}章；"
                "不会删除多余章节，终检和精修仍会覆盖全部正式章节。"
            )

        _step(
            f"无人值守全流程启动：目标第{target:03d}章，"
            f"已有正式正文 {len(existing_numbers)} 章，写作阶段强制使用 default 正常审查。"
        )

        skipped_count = 0
        written_count = 0
        repaired_count = 0

        for chapter in range(1, target + 1):
            chapter_path = chapters_dir / chapter_filename(chapter)
            if chapter_path.exists():
                skipped_count += 1
                continue

            _step(f"无人值守写作：第{chapter:03d}/{target:03d}章...")
            ok = await self.write_chapter(
                chapter,
                mode="default",
                on_step=on_step,
            )
            if ok:
                written_count += 1
                continue

            for attempt in range(1, max_repair_attempts + 1):
                _step(
                    f"无人值守修复：第{chapter:03d}章候选稿未通过，"
                    f"自动修复 {attempt}/{max_repair_attempts}..."
                )
                ok = await self.repair_chapter(
                    chapter,
                    mode="default",
                    on_step=on_step,
                )
                if ok:
                    repaired_count += 1
                    break

            if not ok:
                error(
                    f"无人值守流程停止：第{chapter:03d}章在 "
                    f"{max_repair_attempts} 次自动修复后仍未通过审查。"
                )
                warn("候选稿和审查报告已保留，请检查阻断原因后再继续。")
                return False

        _step(
            "章节阶段完成："
            f"跳过已存在 {skipped_count} 章，新写入 {written_count} 章，"
            f"自动修复通过 {repaired_count} 章。开始最终安全修复..."
        )
        ok_safe = await self.final_safe_repair(on_step=on_step)
        if not ok_safe:
            error("无人值守流程停止：最终安全修复未通过校验，正式正文未覆盖风险修复。")
            return False

        _step("最终安全修复通过，开始终稿精修...")
        ok_polish = await self.final_polish(on_step=on_step)
        if not ok_polish:
            error("无人值守流程停止：终稿精修未通过校验，正式正文未覆盖风险精修。")
            return False

        success(
            "无人值守全流程完成：章节写作、自动修复、最终安全修复、终稿精修均已结束。"
        )
        return True

    def _load_chapter_outline(self, chapter: int) -> dict | None:
        """Load the matching chapter outline from 大纲/outline.json if present."""
        outline_path = self._paths["outline_dir"] / "outline.json"
        data = project_fs.load_json(outline_path)
        if not data:
            return None

        for volume in data.get("volumes", []):
            for item in volume.get("chapters", []):
                if item.get("chapter") == chapter:
                    return item
        return None

    def _load_previous_summary(self, chapter: int) -> str:
        """Load summary of the previous chapter from commit."""
        if chapter <= 1:
            return ""
        prev_commit_path = (
            self._paths["commits_dir"] / f"chapter_{chapter - 1:03d}.commit.json"
        )
        data = project_fs.load_json(prev_commit_path)
        return data.get("summary", "")

    def _load_review_report(self, chapter: int) -> str:
        """Load the latest saved review report for a chapter, if any."""
        path = self._paths["reviews_dir"] / f"chapter_{chapter:03d}_review.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _load_candidate_review_report(self, chapter: int) -> str:
        """Load the latest rejected candidate review for a chapter, if any."""
        path = self._paths["aznovel_dir"] / "candidates" / f"chapter_{chapter:03d}.candidate_review.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _build_rewrite_instruction(
        self,
        *,
        chapter: int,
        modification: str,
        outline: dict | None,
        review_report: str,
        known_entities: list[str] | None = None,
    ) -> str:
        """Build a detailed rewrite brief from user intent, outline, and review.

        The goal is to make the standard rewrite flow behave like a careful human
        editor: always carry forward the outline and the latest concrete review
        evidence, even when the user's request is short.
        """
        parts = ["# 重写任务书"]

        user_request = modification.strip() or "修复本章问题并保持故事连续。"
        parts.append(f"## 用户原始要求\n{user_request}")

        if outline:
            outline_lines = [f"- 章节: 第{chapter:03d}章"]
            if outline.get("title"):
                outline_lines.append(f"- 标题: {outline['title']}")
            if outline.get("goal"):
                outline_lines.append(f"- 本章目标: {outline['goal']}")
            if outline.get("summary"):
                outline_lines.append(f"- 剧情大纲: {outline['summary']}")
            if outline.get("key_nodes"):
                outline_lines.append("- 关键节点:")
                outline_lines.extend(f"  - {item}" for item in outline["key_nodes"])
            if outline.get("ending_feeling"):
                outline_lines.append(f"- 结尾目标: {outline['ending_feeling']}")
            parts.append("## 本章大纲（必须严格遵循）\n" + "\n".join(outline_lines))

        if known_entities:
            parts.append("## 已知实体名（必须保留精确称谓）\n" + "、".join(known_entities))

        if review_report:
            report = review_report
            if len(report) > _REWRITE_REVIEW_REPORT_MAX_CHARS:
                report = (
                    report[:_REWRITE_REVIEW_REPORT_MAX_CHARS]
                    + "\n\n[审查报告过长，后文已截断；优先修复上方所有阻断问题。]"
                )
            parts.append("## 最新审查报告（必须逐条处理）\n" + report)
            strategy_notes = self._repair_strategy_notes(review_report)
            if strategy_notes:
                parts.append(
                    "## 自动诊断重写策略\n"
                    + "\n".join(f"- {note}" for note in strategy_notes)
                )

        parts.append(
            "## 标准执行规则\n"
            "1. 优先修复审查报告中所有 [BLOCKING]、critical、high 问题；这些问题未修复时不得保留原句或同类问题。\n"
            "2. 若审查报告指出大纲合规性问题，必须回到“本章大纲”逐项补齐，不可用相近事件替代指定事件。\n"
            "3. 若审查报告指出实体、时间线、设定或逻辑矛盾，必须统一称谓、因果和设定，不要新增新的矛盾来解释旧矛盾。\n"
            "4. 大纲或已知实体中出现的角色、组织、地点、物品名称必须精确保留；不要用“教授”“儿子”“公司”等泛称替代具体专名。\n"
            "5. 若审查报告指出事件呈现方式偏离大纲（例如写成回忆、录像、新闻转述而不是现场事件），必须把对应事件改成直接发生的场景。\n"
            "6. 若审查报告指出流程、制度或手续无法闭环，不要用更复杂的新设定补洞；优先删掉造成漏洞的细节，改成更简单、可核验的因果链。\n"
            "7. 若审查报告指出 AI 味、套路化比喻、排比推演或展示后解释，必须删除或改写对应证据句，改成具体动作、场景、感官细节或克制叙述。\n"
            "8. 保留原章节中已经有效且未被审查指出的问题段落；不要为了修复局部问题而改写核心剧情走向。\n"
            "9. 输出完整重写后的正文，不要输出章节标题、解释、清单或修订说明。"
        )

        return "\n\n".join(parts)

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
        def _step(msg: str):
            info(msg)
            if on_step:
                on_step(msg)

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
            _step("分析修改影响...")
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
        _step(f"重写第{chapter}章...")
        from aznovel.storage.template_loader import is_drama_genre

        state = self._state_store.load()
        is_drama = is_drama_genre(state.project_info.genre)

        wmin = int(self.word_target * 0.8)
        wmax = int(self.word_target * 1.2)
        prompt_template = _REWRITE_SYSTEM_PROMPT_DRAMA if is_drama else _REWRITE_SYSTEM_PROMPT
        prompt = prompt_template.format(word_min=wmin, word_max=wmax)
        outline = self._load_chapter_outline(chapter)
        review_report = self._load_review_report(chapter)
        rewrite_instruction = self._build_rewrite_instruction(
            chapter=chapter,
            modification=modification,
            outline=outline,
            review_report=review_report,
            known_entities=self._known_entity_names(state),
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"## 原文\n{original_text}\n\n{rewrite_instruction}"},
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
        chapter_brief = self._contract_mgr.generate_chapter_brief(chapter, state, master, outline)
        self._contract_mgr.save_chapter_brief(chapter_brief)

        review_contract = self._contract_mgr.generate_review_contract(
            chapter, state, master, chapter_brief=chapter_brief
        )
        self._contract_mgr.save_review_contract(review_contract)

        report = ""
        if mode != "minimal":
            _step("审查重写内容...")
            review_result = await self._review_engine.review_chapter(
                new_text, review_contract
            )
            report = format_review_report(review_result)

            if not review_result.passed:
                if mode == "default":
                    new_text, review_result, report = await self._repair_review_failures(
                        new_text,
                        review_result,
                        review_contract,
                        report,
                        chapter=chapter,
                        outline=outline,
                        known_entities=self._known_entity_names(state),
                        review_step_message="重新审查重写内容...",
                        on_step=_step,
                    )
                else:
                    warn(f"  发现 {review_result.blocking_count} 个阻断问题，按审查报告润色...")
                    new_text = await self._polish(
                        new_text,
                        report,
                        chapter=chapter,
                        outline=outline,
                        known_entities=self._known_entity_names(state),
                    )
        else:
            review_result = ReviewResult(chapter_number=chapter, passed=True)

        title = chapter_brief.title or f"第{chapter}章"
        if not review_result.passed:
            candidate_path = self._save_candidate(chapter, title, new_text, report)
            warn(
                f"第{chapter}章重写候选稿未通过审查，已保存为候选稿，正式正文未覆盖: {candidate_path}"
            )
            return False, was_cascaded

        if report:
            self._save_review_report(chapter, report)

        # Step 3: Commit the rewritten chapter
        _step("提交重写内容...")
        chapter_brief = self._contract_mgr.generate_chapter_brief(
            chapter, state, master, outline
        )

        commit = await self._commit_service.commit_chapter(
            chapter, new_text, title, review_result
        )

        # Step 4: Save
        _step("保存章节...")
        self._save_chapter(chapter, title, new_text)
        self._clear_candidate(chapter)

        if commit.status == "accepted":
            if was_cascaded and subsequent:
                self._delete_subsequent_chapters(subsequent)
                state.progress.current_chapter = chapter
                self._state_store.save(state)
                _step(f"已删除 {len(subsequent)} 个后续章节，进度已重置为第{chapter}章。")
            success(f"第{chapter}章重写完成！")
            return True, was_cascaded

        warn(f"第{chapter}章已重写并保存，但审查未通过，请继续修复阻断问题。")
        return False, was_cascaded

    async def repair_chapter(
        self,
        chapter: int,
        *,
        mode: str = "default",
        on_step=None,
    ) -> bool:
        """Repair an existing chapter using review findings without full rewrite."""
        def _step(msg: str):
            info(msg)
            if on_step:
                on_step(msg)

        chapter_path = self._paths["chapters_dir"] / chapter_filename(chapter)
        candidate_path = (
            self._paths["aznovel_dir"] / "candidates" / f"chapter_{chapter:03d}.candidate.md"
        )
        if candidate_path.exists():
            source_path = candidate_path
            if chapter_path.exists():
                warn(f"第{chapter}章存在未通过候选稿，将继续修复最近一次候选稿。")
            else:
                warn(f"第{chapter}章正式正文不存在，将修复最近一次候选稿。")
        elif chapter_path.exists():
            source_path = chapter_path
        else:
            error(f"第{chapter}章不存在，无法修复。请用 write 命令新建。")
            return False

        content = source_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        if lines and lines[0].startswith("# "):
            chapter_text = "\n".join(lines[1:]).strip()
        else:
            chapter_text = content.strip()

        state = self._state_store.load()
        master = self._contract_mgr.load_master_setting()
        if not master.genre:
            genre_template = load_genre(resolve_genre_alias(state.project_info.genre))
            master = self._contract_mgr.generate_master_setting(state, genre_template)
            self._contract_mgr.save_master_setting(master)

        outline = self._load_chapter_outline(chapter)
        chapter_brief = self._contract_mgr.generate_chapter_brief(
            chapter, state, master, outline
        )
        self._contract_mgr.save_chapter_brief(chapter_brief)
        review_contract = self._contract_mgr.generate_review_contract(
            chapter, state, master, chapter_brief=chapter_brief
        )
        self._contract_mgr.save_review_contract(review_contract)

        _step(f"审查第{chapter}章当前内容...")
        review_result = await self._review_engine.review_chapter(
            chapter_text, review_contract
        )
        previous_review_report = "\n\n".join(
            report
            for report in (
                self._load_candidate_review_report(chapter),
                self._load_review_report(chapter),
            )
            if report
        )
        review_result = self._with_candidate_guards(
            chapter=chapter,
            result=review_result,
            candidate_text=chapter_text,
            reference_text=chapter_text,
            outline=outline,
            known_entities=self._known_entity_names(state),
            previous_review_report=previous_review_report,
        )
        report = format_review_report(review_result)
        self._save_review_report(chapter, report)

        if not review_result.passed and mode == "default":
            chapter_text, review_result, report = await self._repair_review_failures(
                chapter_text,
                review_result,
                review_contract,
                report,
                chapter=chapter,
                outline=outline,
                known_entities=self._known_entity_names(state),
                review_step_message=f"重新审查第{chapter}章修复内容...",
                on_step=_step,
            )
        elif not review_result.passed:
            warn(f"  发现 {review_result.blocking_count} 个阻断问题，按审查报告润色修复...")
            chapter_text = await self._polish(
                chapter_text,
                report,
                chapter=chapter,
                outline=outline,
                known_entities=self._known_entity_names(state),
            )

        title = chapter_brief.title or f"第{chapter}章"
        if not review_result.passed:
            candidate_path = self._save_candidate(chapter, title, chapter_text, report)
            warn(
                f"第{chapter}章修复候选稿未通过审查，已保存为候选稿，正式正文未覆盖: {candidate_path}"
            )
            return False

        if report:
            self._save_review_report(chapter, report)

        _step("提交修复内容...")
        commit = await self._commit_service.commit_chapter(
            chapter, chapter_text, title, review_result
        )

        _step("保存章节...")
        self._save_chapter(chapter, title, chapter_text)
        self._clear_candidate(chapter)

        if commit.status == "accepted":
            success(f"第{chapter}章修复完成！")
            return True

        warn(f"第{chapter}章已修复并保存，但审查未通过，请继续修复阻断问题。")
        return False

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
