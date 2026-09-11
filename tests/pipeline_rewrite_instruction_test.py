import asyncio

from aznovel.core.pipeline import WritingPipeline


class DummyProvider:
    pass


def _write_test_chapter(root, chapter: int, title: str, body: str) -> None:
    chapters_dir = root / "正文"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    (chapters_dir / f"第{chapter:03d}章.md").write_text(
        f"# {title}\n\n{body}\n",
        encoding="utf-8",
    )


def test_rewrite_instruction_includes_outline_and_review(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)

    instruction = pipeline._build_rewrite_instruction(
        chapter=3,
        modification="修复阻断问题",
        outline={
            "title": "争议",
            "goal": "揭示科学界对禾苗的质疑及异变初现",
            "summary": "科学家质疑禾苗基因异常及长期安全性，汪禾回应绝对安全。",
            "key_nodes": ["周小禾夜间说梦话", "禾苗2.0版本上市"],
        },
        review_report="# 审查报告\n\n### 问题 1 [BLOCKING]\n缺失基因异常质疑。",
        known_entities=["汪禾", "周小禾"],
    )

    assert "## 用户原始要求\n修复阻断问题" in instruction
    assert "## 本章大纲（必须严格遵循）" in instruction
    assert "科学家质疑禾苗基因异常及长期安全性" in instruction
    assert "## 最新审查报告（必须逐条处理）" in instruction
    assert "## 已知实体名（必须保留精确称谓）" in instruction
    assert "不要用“教授”“儿子”“公司”等泛称替代" in instruction
    assert "[BLOCKING]" in instruction
    assert "优先修复审查报告中所有 [BLOCKING]" in instruction


def test_load_review_report_returns_latest_report(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    review_dir = tmp_path / "审查报告"
    review_dir.mkdir()
    (review_dir / "chapter_003_review.md").write_text("第3章审查", encoding="utf-8")

    assert pipeline._load_review_report(3) == "第3章审查"
    assert pipeline._load_review_report(4) == ""


def test_polish_instruction_is_targeted_to_review_issues(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)

    instruction = pipeline._build_polish_instruction(
        chapter_text="原章节正文",
        review_report="# 审查报告\n\n### 问题 1 [BLOCKING]\nAI味句子需要删除。",
        chapter=4,
        outline={"title": "优化", "summary": "汪禾反对2.0仓促推出。"},
        known_entities=["汪禾", "周小禾"],
    )

    assert "## 审查报告（必须逐条修复）" in instruction
    assert "[BLOCKING]" in instruction
    assert "被报告点名的证据句必须删除" in instruction
    assert "必须精确保留" in instruction
    assert "输出完整修复后的正文，是为了覆盖保存" in instruction
    assert "原章节正文" in instruction


def test_apply_text_edits_only_applies_unique_matches(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)

    text, applied, errors = pipeline._apply_text_edits(
        "甲句。乙句。乙句。",
        [
            {"old": "甲句。", "new": "甲句修复。", "reason": "唯一匹配"},
            {"old": "乙句。", "new": "乙句修复。", "reason": "重复匹配"},
            {"old": "丙句。", "new": "丙句修复。", "reason": "不存在"},
        ],
    )

    assert applied == 1
    assert text == "甲句修复。乙句。乙句。"
    assert len(errors) == 2


def test_local_patch_instruction_requires_exact_old_new(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)

    instruction = pipeline._build_local_patch_instruction(
        chapter_text="周小禾坐在桌前。",
        review_report="# 审查报告\n\n### 问题 1 [BLOCKING]\n角色混乱。",
        chapter=4,
        outline={"title": "优化", "summary": "儿子食用2.0后症状加重。"},
        known_entities=["周也", "周小禾"],
    )

    assert "old 必须来自下方原文，且在原文中只出现一次" in instruction
    assert "不超过 8 个 old/new 补丁" in instruction
    assert "周小禾坐在桌前。" in instruction


def test_repair_strategy_notes_use_cross_genre_tactics(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "大纲要求关键事件在现场直接发生，但正文实际只是一条新闻推送和录像转述。"
        "主角预算不足，库存也只剩一件，后文却突然写成还有很多备用物资，数量不闭合。"
    )

    instruction = pipeline._build_polish_instruction(
        chapter_text="正文",
        review_report=report,
        chapter=5,
        outline={"summary": "关键事件在现场发生，主角被迫处理资源不足。"},
        known_entities=["主角", "远星公司"],
    )

    assert "自动诊断修复策略" in instruction
    assert "不能只通过新闻、推送、录像、回忆或他人口述完成" in instruction
    assert "资源、库存、时间、钱款或物资不足类冲突" in instruction
    assert "汪禾" not in instruction
    assert "周小禾" not in instruction


def test_repair_strategy_notes_handle_setting_boundary_and_premature_reveal(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "能力设定规则边界被越权，角色直接得到规则不允许的信息。"
        "关键真相按大纲应在结尾才揭示，正文中段却提前暴露，破坏悬念节奏。"
    )

    instruction = pipeline._build_local_patch_instruction(
        chapter_text="正文",
        review_report=report,
        chapter=6,
        outline={"summary": "结尾才揭示关键真相。"},
        known_entities=["主角"],
    )

    assert "身份、职业、能力或世界观规则越界" in instruction
    assert "把行为、信息来源和推理过程收回到该限制内" in instruction
    assert "信息暴露过早" in instruction
    assert "降级成可疑但未定性的线索" in instruction


def test_repair_strategy_notes_handle_chapter_overrun_and_timing(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "第8章大纲要求结尾停在门外逼近的悬念，但正文提前写出后续章已经完成的逃离结果。"
        "前文说手续至少需要几小时，后文却几分钟内完成，时间线冲突。"
    )

    instruction = pipeline._build_local_patch_instruction(
        chapter_text="正文",
        review_report=report,
        chapter=8,
        outline={"summary": "结尾停在威胁逼近，结果尚未完成。"},
        known_entities=["主角"],
    )

    assert "章节越界或结尾推进过头" in instruction
    assert "收回到本章大纲指定的悬念点" in instruction
    assert "时间线或耗时矛盾" in instruction


def test_tail_repair_detects_chapter_overrun_boundary_from_evidence(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "第8章大纲要求停在威胁逼近，但正文提前写出后续章已经完成的逃离。\n"
        "- **证据**: > 话音未落，门外传来巨响。主角抱着同伴逃出设施，所有问题已经解决。"
    )
    chapter_text = (
        "主角还在核对倒计时。\n\n"
        "话音未落，门外传来巨响。主角抱着同伴逃出设施，所有问题已经解决。"
    )

    assert pipeline._is_chapter_overrun_report(report) is True
    start = pipeline._find_tail_repair_start(chapter_text, report)
    assert start == chapter_text.index("话音未落")


def test_tail_repair_boundary_falls_back_to_late_chapter_when_report_has_no_quote(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = "第8章大纲要求停在悬念，但正文提前写出后续结果，章节越界。"
    chapter_text = (
        "第一段。\n\n"
        "第二段。\n\n"
        "第三段。\n\n"
        "第四段写出后续结果。\n\n"
        "第五段继续收束。"
    )

    start = pipeline._find_tail_repair_start(chapter_text, report)
    assert start == chapter_text.index("第四段")


def test_tail_repair_instruction_stays_generic(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = "大纲要求停在威胁逼近，但正文写成威胁已经解决。"
    chapter_text = (
        "门外的声音越来越近。\n\n"
        "门彻底打开，主角已经离开。"
    )

    instruction = pipeline._build_tail_repair_instruction(
        prefix=chapter_text[: chapter_text.index("门彻底打开")].strip(),
        tail=chapter_text[chapter_text.index("门彻底打开"):],
        review_report=report,
        chapter=8,
        outline={"summary": "结尾停在威胁逼近。"},
        known_entities=["主角"],
    )

    assert "停在本章大纲指定的悬念" in instruction
    assert "不要写完后续章才该发生的结果" in instruction
    assert "禾苗" not in instruction


def test_blocking_evidence_texts_strip_quote_prefix(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "### 🔴 问题 1 [BLOCKING]\n"
        "- **类别**: outline\n"
        "- **描述**: 汪禾状态偏离正在研究解药。\n"
        "- **证据**: > 正文结尾：“以及汪禾绝望的干呕声。”"
    )

    assert pipeline._blocking_evidence_texts(report) == ["以及汪禾绝望的干呕声。"]


def test_blocking_evidence_texts_keep_long_causal_evidence(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    evidence = (
        "角色甲的牺牲，不仅是因为他制造了气味干扰，更因为他刚刚补充过能量，"
        "被错误写成了“高能量目标”。那次补给的代价，就是让他成为了怪物首选的攻击目标。"
    )
    report = (
        "### 🟠 问题 1 [BLOCKING]\n"
        "- **类别**: logic\n"
        "- **描述**: 刚补充能量就成为高能量目标，与资源稀缺生存常态逻辑冲突。\n"
        f"- **证据**: > {evidence}"
    )

    assert pipeline._blocking_evidence_texts(report) == [evidence]


def test_micro_evidence_patch_instruction_targets_only_evidence(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    instruction = pipeline._build_micro_evidence_patch_instruction(
        evidence="以及汪禾绝望的干呕声。",
        review_report=(
            "### 🔴 问题 1 [BLOCKING]\n"
            "- **描述**: 汪禾应处于研究解药状态，但结尾写成绝望干呕。"
        ),
        outline={"summary": "汪禾正研究解药但需时间。结尾禾苗包围实验室。"},
    )

    assert "待替换证据原文" in instruction
    assert "以及汪禾绝望的干呕声。" in instruction
    assert "只替换这一个短文本" in instruction


def test_focused_patch_windows_find_blocking_evidence_paragraphs(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    chapter_text = (
        "周也收紧雨衣。\n\n"
        "周小禾坐在沙发上，瞳孔深处有微弱的荧光在流转，嘴角牵出一个生硬的弧度：“它们在唱歌。”\n\n"
        "窗外藤蔓敲打玻璃。\n\n"
        "周小禾看着手臂上清晰的绿色纹路，低声说：“它们说，不冷了。”"
    )
    report = (
        "### 🟠 问题 1 [BLOCKING]\n"
        "- **类别**: character\n"
        "- **描述**: 周小禾表现出明显的被同化症状，提前暴露儿子的异变状态。\n"
        "- **证据**: > 周小禾坐在沙发上，瞳孔深处有微弱的荧光在流转，嘴角牵出一个生硬的弧度：“它们在唱歌。”"
    )

    windows = pipeline._focused_patch_windows(
        chapter_text,
        report,
        known_entities=["周也", "周小禾"],
    )

    assert windows
    assert "瞳孔深处有微弱的荧光" in windows[0]


def test_deterministic_review_patch_fixes_name_inconsistency(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)

    text, applied = pipeline._apply_deterministic_review_patches(
        "前面的老张回过头。周也看着老赵被拖出大门。",
        "前文刚设定老张被拖走，后文紧接着称呼其为老赵，属于人物称呼前后不一致的叙事断裂问题。",
    )

    assert applied == 1
    assert text == "前面的老张回过头。周也看着老张被拖出大门。"


def test_deterministic_review_patch_leaves_story_repairs_to_llm(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    text = "主角直接凭能力说出了路线、数量和动机。"
    report = (
        "### 🔴 问题 1 [BLOCKING]\n"
        "- **类别**: setting\n"
        "- **描述**: 能力边界被越权，具体修法需要结合大纲和当前场景。"
    )

    patched, applied = pipeline._apply_deterministic_review_patches(text, report)

    assert applied == 0
    assert patched == text


def test_review_fragments_include_quoted_source_text(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "### 🟠 问题 1 [BLOCKING]\n"
        "- **证据**: > 大纲要求：‘主角仍在现场却未察觉异常。’ "
        "正文实际情况：‘主角接过文件，转身走向自己的办公区。’随后视角切换至配角。"
    )

    fragments = pipeline._review_evidence_fragments(report)

    assert "主角接过文件，转身走向自己的办公区。" in fragments
    assert "转身走向自己的办公区" in fragments


def test_focused_patch_windows_include_adjacent_paragraphs(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    text = (
        "主角沉默了两秒。\n\n"
        "“知道了。卷宗归档吧。”她接过文件，转身走向自己的办公区。\n\n"
        "配角在背后欲言又止，最终只是看着主角的背影消失在转角。"
    )
    report = (
        "### 🟠 问题 1 [BLOCKING]\n"
        "- **描述**: 大纲要求主角未察觉，但正文让主角离场，视角切换到配角。\n"
        "- **证据**: > 正文实际情况：‘主角接过文件，转身走向自己的办公区。’随后视角切换至配角。"
    )

    windows = pipeline._focused_patch_windows(
        text,
        report,
        known_entities=["主角"],
    )

    assert any("转身走向自己的办公区" in window and "配角在背后" in window for window in windows)


def test_entity_guard_blocks_missing_required_entity(tmp_path) -> None:
    from aznovel.models.review import ReviewResult

    pipeline = WritingPipeline(DummyProvider(), tmp_path)

    guarded = pipeline._with_candidate_guards(
        chapter=4,
        result=ReviewResult(chapter_number=4, passed=True),
        candidate_text="周小禾拉着推车离开配给站。",
        reference_text="周也拉着推车离开配给站。",
        outline={"summary": "周也配送时发现2.0气息奇怪。"},
        known_entities=["周也", "周小禾"],
    )

    assert guarded.passed is False
    assert guarded.blocking_count == 1
    assert guarded.issues[0].category == "entity_guard"


def test_candidate_guard_blocks_missing_research_material(tmp_path) -> None:
    from aznovel.models.review import ReviewResult

    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    result = ReviewResult(chapter_number=9, passed=True)
    result.compute_derived()

    guarded = pipeline._with_candidate_guards(
        chapter=9,
        result=result,
        candidate_text="周也带着儿子逃离，只摸到急救包里的逆转录酶。",
        reference_text="周也带着儿子逃离。",
        outline={"summary": "周也带着儿子和汪禾的研究资料逃离。"},
        known_entities=["周也"],
    )

    assert guarded.passed is False
    assert guarded.blocking_count == 1
    assert guarded.issues[0].category == "outline_object_guard"
    assert "关键道具守护失败" in guarded.summary


def test_candidate_guard_blocks_stale_blocking_evidence(tmp_path) -> None:
    from aznovel.models.review import ReviewResult

    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    evidence = (
        "角色甲的牺牲，不仅是因为他制造了气味干扰，更因为他刚刚补充过能量，"
        "被错误写成了“高能量目标”。那次补给的代价，就是让他成为了怪物首选的攻击目标。"
    )
    previous_report = (
        "### 🟠 问题 1 [BLOCKING]\n"
        "- **类别**: logic\n"
        "- **描述**: 刚补充能量就成为高能量目标，与资源稀缺生存常态逻辑冲突。\n"
        f"- **证据**: > {evidence}"
    )
    result = ReviewResult(chapter_number=9, passed=True)
    result.compute_derived()

    guarded = pipeline._with_candidate_guards(
        chapter=9,
        result=result,
        candidate_text=f"前文。\n\n{evidence}\n\n后文。",
        reference_text=f"前文。\n\n{evidence}\n\n后文。",
        outline=None,
        known_entities=[],
        previous_review_report=previous_report,
    )

    assert guarded.passed is False
    assert guarded.blocking_count == 1
    assert guarded.issues[0].category == "stale_blocking_evidence"
    assert "旧阻断证据仍保留" in guarded.summary


def test_repair_improvement_must_reduce_blockers(tmp_path) -> None:
    from aznovel.models.review import ReviewIssue, ReviewResult

    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    baseline = ReviewResult(
        chapter_number=4,
        issues=[
            ReviewIssue(severity="high", category="logic", blocking=True),
            ReviewIssue(severity="high", category="outline", blocking=True),
        ],
    )
    baseline.compute_derived()

    same = ReviewResult(
        chapter_number=4,
        issues=[
            ReviewIssue(severity="high", category="logic", blocking=True),
            ReviewIssue(severity="high", category="entity_guard", blocking=True),
        ],
    )
    same.compute_derived()

    better = ReviewResult(
        chapter_number=4,
        issues=[ReviewIssue(severity="high", category="logic", blocking=True)],
    )
    better.compute_derived()

    assert pipeline._is_repair_improvement(same, baseline) is False
    assert pipeline._is_repair_improvement(better, baseline) is True


def test_repair_improvement_can_reduce_nonblocking_risk(tmp_path) -> None:
    from aznovel.models.review import ReviewIssue, ReviewResult

    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    baseline = ReviewResult(
        chapter_number=5,
        issues=[
            ReviewIssue(severity="high", category="logic", blocking=True),
            ReviewIssue(severity="medium", category="ai_flavor", blocking=False),
        ],
    )
    baseline.compute_derived()

    cleaner = ReviewResult(
        chapter_number=5,
        issues=[ReviewIssue(severity="high", category="logic", blocking=True)],
    )
    cleaner.compute_derived()

    noisier = ReviewResult(
        chapter_number=5,
        issues=[
            ReviewIssue(severity="high", category="logic", blocking=True),
            ReviewIssue(severity="high", category="outline", blocking=True),
        ],
    )
    noisier.compute_derived()

    assert pipeline._is_repair_improvement(cleaner, baseline) is True
    assert pipeline._is_repair_improvement(noisier, baseline) is False


def test_repair_improvement_accepts_smaller_issue_list_with_same_blockers(tmp_path) -> None:
    from aznovel.models.review import ReviewIssue, ReviewResult

    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    baseline = ReviewResult(
        chapter_number=5,
        issues=[
            ReviewIssue(severity="high", category="logic", blocking=True),
            ReviewIssue(severity="low", category="style", blocking=False),
            ReviewIssue(severity="low", category="continuity", blocking=False),
            ReviewIssue(severity="low", category="ai_flavor", blocking=False),
            ReviewIssue(severity="low", category="setting", blocking=False),
        ],
    )
    baseline.compute_derived()

    smaller = ReviewResult(
        chapter_number=5,
        issues=[ReviewIssue(severity="critical", category="logic", blocking=True)],
    )
    smaller.compute_derived()

    much_riskier = ReviewResult(
        chapter_number=5,
        issues=[
            ReviewIssue(severity="critical", category="logic", blocking=True),
            ReviewIssue(severity="critical", category="outline", blocking=False),
        ],
    )
    much_riskier.compute_derived()

    assert pipeline._is_repair_improvement(smaller, baseline) is True
    assert pipeline._is_repair_improvement(much_riskier, baseline) is False


def test_repair_improvement_rejects_same_blocker_with_more_issues(tmp_path) -> None:
    from aznovel.models.review import ReviewIssue, ReviewResult

    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    baseline = ReviewResult(
        chapter_number=5,
        issues=[
            ReviewIssue(severity="high", category="logic", blocking=True),
            ReviewIssue(severity="critical", category="character", blocking=False),
            ReviewIssue(severity="high", category="outline", blocking=False),
        ],
    )
    baseline.compute_derived()

    noisy_candidate = ReviewResult(
        chapter_number=5,
        issues=[
            ReviewIssue(severity="high", category="logic", blocking=True),
            ReviewIssue(severity="low", category="ai_flavor", blocking=False),
            ReviewIssue(severity="low", category="style", blocking=False),
            ReviewIssue(severity="low", category="continuity", blocking=False),
            ReviewIssue(severity="low", category="logic", blocking=False),
        ],
    )
    noisy_candidate.compute_derived()

    assert pipeline._review_risk_score(noisy_candidate) < pipeline._review_risk_score(baseline)
    assert pipeline._is_repair_improvement(noisy_candidate, baseline) is False


async def test_repair_candidates_do_not_overwrite_official_review(tmp_path) -> None:
    from aznovel.models.contract import ReviewContract
    from aznovel.models.review import ReviewIssue, ReviewResult

    pipeline = WritingPipeline(DummyProvider(), tmp_path)

    baseline = ReviewResult(
        chapter_number=4,
        issues=[ReviewIssue(severity="high", category="logic", blocking=True)],
    )
    baseline.compute_derived()

    async def transactional_local_patch_repair(
        chapter_text, review_result, review_contract, review_report, **kwargs
    ):
        return chapter_text, review_result, review_report, 0, 1

    async def polish(chapter_text, review_report, **kwargs):
        return "polished text"

    pipeline._transactional_local_patch_repair = transactional_local_patch_repair
    pipeline._polish = polish

    _, final_result, final_report = await pipeline._repair_review_failures(
        "base text",
        baseline,
        ReviewContract(chapter_number=4),
        "official current report",
        chapter=4,
        outline=None,
        known_entities=[],
        review_step_message="重新审查",
    )

    assert final_result.blocking_count == 1
    assert "official current report" in final_report
    assert not (tmp_path / "审查报告" / "chapter_004_review.md").exists()


async def test_repair_chapter_continues_from_candidate_when_official_exists(tmp_path) -> None:
    from types import SimpleNamespace

    from aznovel.core.contract_manager import ContractManager
    from aznovel.models.contract import MasterSetting
    from aznovel.models.project import ProjectInfo, ProjectState, ProtagonistState
    from aznovel.models.review import ReviewResult
    from aznovel.storage import project_fs
    from aznovel.storage.state_store import StateStore

    project_fs.ensure_project_dirs(tmp_path)
    StateStore(tmp_path).save(
        ProjectState(
            project_info=ProjectInfo(title="测试项目", genre="urban"),
            protagonist=ProtagonistState(name="主角"),
        )
    )
    ContractManager(tmp_path).save_master_setting(MasterSetting(genre="urban"))
    _write_test_chapter(tmp_path, 3, "正式", "正式正文")

    candidates_dir = tmp_path / ".aznovel" / "candidates"
    candidates_dir.mkdir(parents=True)
    candidate_path = candidates_dir / "chapter_003.candidate.md"
    candidate_review_path = candidates_dir / "chapter_003.candidate_review.md"
    candidate_path.write_text("# 候选\n\n候选正文\n", encoding="utf-8")
    candidate_review_path.write_text("候选审查", encoding="utf-8")

    class FakeReviewEngine:
        def __init__(self) -> None:
            self.seen_text = ""

        async def review_chapter(self, chapter_text, contract):
            self.seen_text = chapter_text
            return ReviewResult(chapter_number=3, passed=True)

    class FakeCommitService:
        async def commit_chapter(self, *args, **kwargs):
            return SimpleNamespace(status="accepted")

    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    fake_review = FakeReviewEngine()
    pipeline._review_engine = fake_review
    pipeline._commit_service = FakeCommitService()

    ok = await pipeline.repair_chapter(3)

    assert ok is True
    assert fake_review.seen_text == "候选正文"
    assert not candidate_path.exists()
    assert not candidate_review_path.exists()


async def test_transactional_repair_uses_structured_llm_task_first(tmp_path) -> None:
    from aznovel.models.contract import ReviewContract
    from aznovel.models.review import ReviewIssue, ReviewResult

    original = "她直接凭能力说出了路线、数量和动机。"
    repaired = "她先核对外部记录，再只用能力确认对方刚刚说出的字面回答。"

    class StructuredProvider:
        def __init__(self):
            self.calls = []

        async def chat_json(self, messages, **kwargs):
            self.calls.append(messages[0]["content"])
            if "修复规划器" in messages[0]["content"]:
                return {
                    "tasks": [
                        {
                            "issue_id": "I1",
                            "blocking": True,
                            "category": "setting",
                            "violated_contract": "能力只能判断字面回答",
                            "evidence": [original],
                            "paragraph_indexes": [1],
                            "required_fix": "把具体细节来源改为外部证据，能力只确认字面回答。",
                            "success_criteria": ["不再让能力直接给出路线和数量"],
                        }
                    ]
                }
            return {
                "edits": [
                    {
                        "old": original,
                        "new": repaired,
                        "reason": "I1: 约束能力边界",
                    }
                ]
            }

    class FakeReviewEngine:
        async def review_chapter(self, chapter_text, contract):
            if "外部记录" in chapter_text:
                result = ReviewResult(chapter_number=1, passed=True)
            else:
                result = ReviewResult(
                    chapter_number=1,
                    issues=[
                        ReviewIssue(
                            severity="critical",
                            category="setting",
                            blocking=True,
                        )
                    ],
                )
            result.compute_derived()
            return result

    provider = StructuredProvider()
    pipeline = WritingPipeline(provider, tmp_path)
    pipeline._review_engine = FakeReviewEngine()
    baseline = ReviewResult(
        chapter_number=1,
        issues=[ReviewIssue(severity="critical", category="setting", blocking=True)],
    )
    baseline.compute_derived()

    text, result, report, accepted, rejected = await pipeline._transactional_local_patch_repair(
        original,
        baseline,
        ReviewContract(chapter_number=1),
        "# 审查报告\n### 问题 1 [BLOCKING]\n能力被写成越权推理系统。",
        chapter=1,
        outline={"summary": "能力只能判断字面回答。"},
        known_entities=["主角"],
        reference_text=original,
    )

    assert accepted == 1
    assert rejected == 0
    assert result.passed is True
    assert text == repaired
    assert any("修复规划器" in call for call in provider.calls)


async def test_transactional_patch_rejects_worsening_edits(tmp_path) -> None:
    from aznovel.models.contract import ReviewContract
    from aznovel.models.review import ReviewIssue, ReviewResult

    class PatchProvider:
        async def chat_json(self, *args, **kwargs):
            return {"edits": [{"old": "原句。", "new": "坏补丁。"}]}

    class FakeReviewEngine:
        async def review_chapter(self, chapter_text, contract):
            if "坏补丁" in chapter_text:
                result = ReviewResult(
                    chapter_number=5,
                    issues=[
                        ReviewIssue(severity="high", category="logic", blocking=True),
                        ReviewIssue(severity="high", category="outline", blocking=True),
                    ],
                )
            else:
                result = ReviewResult(
                    chapter_number=5,
                    issues=[
                        ReviewIssue(severity="high", category="logic", blocking=True)
                    ],
                )
            result.compute_derived()
            return result

    pipeline = WritingPipeline(PatchProvider(), tmp_path)
    pipeline._review_engine = FakeReviewEngine()
    baseline = ReviewResult(
        chapter_number=5,
        issues=[ReviewIssue(severity="high", category="logic", blocking=True)],
    )
    baseline.compute_derived()

    text, result, report, accepted, rejected = await pipeline._transactional_local_patch_repair(
        "原句。",
        baseline,
        ReviewContract(chapter_number=5),
        "# 审查报告\n阻断问题",
        chapter=5,
        outline=None,
        known_entities=[],
        reference_text="原句。",
    )

    assert text == "原句。"
    assert result.blocking_count == 1
    assert accepted == 0
    assert rejected == 1
    assert "坏补丁" not in report


async def test_single_blocker_transaction_limits_local_patch_attempts(tmp_path) -> None:
    from aznovel.models.contract import ReviewContract
    from aznovel.models.review import ReviewIssue, ReviewResult

    class PatchProvider:
        async def chat_json(self, *args, **kwargs):
            return {
                "edits": [
                    {"old": "原句。", "new": f"坏补丁{i}。"}
                    for i in range(1, 7)
                ]
            }

    class FakeReviewEngine:
        def __init__(self):
            self.calls = 0

        async def review_chapter(self, chapter_text, contract):
            self.calls += 1
            result = ReviewResult(
                chapter_number=5,
                issues=[
                    ReviewIssue(severity="high", category="logic", blocking=True),
                    ReviewIssue(severity="low", category="style", blocking=False),
                ],
            )
            result.compute_derived()
            return result

    pipeline = WritingPipeline(PatchProvider(), tmp_path)
    fake_review = FakeReviewEngine()
    pipeline._review_engine = fake_review
    baseline = ReviewResult(
        chapter_number=5,
        issues=[ReviewIssue(severity="high", category="logic", blocking=True)],
    )
    baseline.compute_derived()

    text, result, report, accepted, rejected = await pipeline._transactional_local_patch_repair(
        "原句。",
        baseline,
        ReviewContract(chapter_number=5),
        "# 审查报告\n### 问题 1 [BLOCKING]\n阻断问题",
        chapter=5,
        outline=None,
        known_entities=[],
        reference_text="原句。",
    )

    assert text == "原句。"
    assert result.blocking_count == 1
    assert accepted == 0
    assert rejected == 3
    assert fake_review.calls == 3


async def test_multi_blocker_transaction_stops_after_reject_streak(tmp_path) -> None:
    from aznovel.models.contract import ReviewContract
    from aznovel.models.review import ReviewIssue, ReviewResult

    class PatchProvider:
        async def chat_json(self, *args, **kwargs):
            return {
                "edits": [
                    {"old": "原句。", "new": f"坏补丁{i}。"}
                    for i in range(1, 8)
                ]
            }

    class FakeReviewEngine:
        def __init__(self):
            self.calls = 0

        async def review_chapter(self, chapter_text, contract):
            self.calls += 1
            result = ReviewResult(
                chapter_number=7,
                issues=[
                    ReviewIssue(severity="high", category="logic", blocking=True),
                    ReviewIssue(severity="high", category="outline", blocking=True),
                    ReviewIssue(severity="high", category="character", blocking=True),
                ],
            )
            result.compute_derived()
            return result

    pipeline = WritingPipeline(PatchProvider(), tmp_path)
    fake_review = FakeReviewEngine()
    pipeline._review_engine = fake_review
    baseline = ReviewResult(
        chapter_number=7,
        issues=[
            ReviewIssue(severity="high", category="logic", blocking=True),
            ReviewIssue(severity="high", category="outline", blocking=True),
        ],
    )
    baseline.compute_derived()

    text, result, report, accepted, rejected = await pipeline._transactional_local_patch_repair(
        "原句。",
        baseline,
        ReviewContract(chapter_number=7),
        "# 审查报告\n### 问题 1 [BLOCKING]\n阻断问题",
        chapter=7,
        outline=None,
        known_entities=[],
        reference_text="原句。",
    )

    assert text == "原句。"
    assert result.blocking_count == 2
    assert accepted == 0
    assert rejected == 4
    assert fake_review.calls == 4


def test_final_safe_issue_detection_builds_cross_chapter_ledger(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    issues = pipeline._detect_final_safe_issues(
        {
            3: "掌心的纹路里，有一抹洗不掉的淡绿色，隐隐发出微光。",
            4: "1.0阶段遇到的排异反应不是bug。那层微弱的荧光已经蔓延到了手腕。",
            5: "手背上的青紫斑块似乎比刚才更鲜艳了一些。",
            6: (
                "周也的手指悬在旋钮上，指节因用力而泛白。赵德柱在监控画面里变成青紫色人形茧的场景像烙铁一样印在视网膜上，"
                "他下意识地摩挲着自己的小臂，那里只有粗糙的皮肤和紧绷的肌肉。他绝不能让那场异变在儿子身上重演。"
            ),
            8: "“禾苗1.0是安全的。”汪禾的视线落在试管上，像在看一个被谋杀的孩子，\n一根纤细的藤蔓从操作台边缘探出头来，像一条吐信的毒蛇，缓缓伸向了那支装着逆转录酶的空试管。",
            9: (
                "藤蔓的尖端像一根急促探动的盲蛇，距离操作台上的逆转录酶试管不足五厘米。玻璃管壁折射着应急灯惨绿的光，里面透明的液体是周小禾仅存的概率。\n"
                "汪禾的手指搭上了那管逆转录酶。周也的肌肉瞬间绷紧，但汪禾没有将试管递给他，而是猛地将其塞进了周也胸前的急救包，拉链拉上的声音在嘈杂中异常刺耳。\n"
                "急救包里的逆转录酶和汪禾塞进来的防水资料袋硌着他的肋骨。酶还在，但他并没有给周小禾使用。"
            ),
            10: (
                "实验室里的奇迹并未发生，逆转录酶没有起效。"
                "这是汪禾用命换来的，是此刻方圆百里内唯一能让他们迅速“长肉”的东西。"
                "藤蔓会循着养分的浓度精准定位。引导藤蔓精准收割。"
                "“爸……”周小禾喘息着，声音微弱得几乎听不见，“我是不是要死了？”"
                "“不会。”周也把手从兜里抽出来，没有带出凝胶。"
            ),
        }
    )

    issue_ids = {issue["id"] for issue in issues}
    assert "C06_ZHOU_INFECTION_CONTINUITY" in issue_ids
    assert "C08_HM10_ABSOLUTE_SAFETY_TENSION" in issue_ids
    assert "C08_RT_TUBE_EMPTY_CONFLICT" in issue_ids
    assert "C09_RESEARCH_BAG_SETUP_MISSING" in issue_ids
    assert "C10_RT_NOT_USED_BUT_FAILED" in issue_ids
    assert "C10_GLUCOSE_GEL_SOURCE_CONFLICT" in issue_ids
    assert "C10_TERMINOLOGY_ACCOUNTANT_OOC" in issue_ids
    assert "C10_ENDING_DIALOGUE_ALIGNMENT" in issue_ids


def test_final_safe_repair_applies_only_validated_small_patches(tmp_path) -> None:
    _write_test_chapter(
        tmp_path,
        3,
        "异变初现",
        "周也低头看了一眼自己的手。掌心的纹路里，有一抹洗不掉的淡绿色，那是上午搬货时沾上的黏液。他用力搓了搓，皮肤泛红，那抹绿色却仿佛渗进了肌理，随着脉搏的跳动，隐隐发出微光。",
    )
    _write_test_chapter(
        tmp_path,
        4,
        "版本更新",
        "1.0阶段遇到的排异反应不是bug。周也低头看向自己的手，那层微弱的荧光已经蔓延到了手腕，与皮肤下的青紫色血管交织在一起。",
    )
    _write_test_chapter(
        tmp_path,
        5,
        "公开攻击",
        "房间里死一般的寂静。周也慢慢低下头，看向自己的双手。手背上的青紫斑块似乎比刚才更鲜艳了一些，边缘的荧光在昏暗的室内隐约可辨。",
    )
    _write_test_chapter(
        tmp_path,
        6,
        "逃亡",
        (
            "周也的手指悬在旋钮上，指节因用力而泛白。赵德柱在监控画面里变成青紫色人形茧的场景像烙铁一样印在视网膜上，"
            "他下意识地摩挲着自己的小臂，那里只有粗糙的皮肤和紧绷的肌肉。他绝不能让那场异变在儿子身上重演。"
        ),
    )
    _write_test_chapter(
        tmp_path,
        8,
        "实验室",
        (
            "“禾苗1.0是安全的。”汪禾的视线落在试管上，像在看一个被谋杀的孩子，继续解释。\n\n"
            "一根纤细的藤蔓从操作台边缘探出头来，像一条吐信的毒蛇，缓缓伸向了那支装着逆转录酶的空试管。"
        ),
    )
    _write_test_chapter(
        tmp_path,
        9,
        "代价",
        (
            "藤蔓的尖端像一根急促探动的盲蛇，距离操作台上的逆转录酶试管不足五厘米。玻璃管壁折射着应急灯惨绿的光，里面透明的液体是周小禾仅存的概率。\n\n"
            "汪禾的手指搭上了那管逆转录酶。周也的肌肉瞬间绷紧，但汪禾没有将试管递给他，而是猛地将其塞进了周也胸前的急救包，拉链拉上的声音在嘈杂中异常刺耳。\n\n"
            "急救包里的逆转录酶和汪禾塞进来的防水资料袋硌着他的肋骨。酶还在，但他并没有给周小禾使用。"
        ),
    )
    _write_test_chapter(
        tmp_path,
        10,
        "末日口粮",
        (
            "实验室里的奇迹并未发生，逆转录酶没有起效。\n\n"
            "这是汪禾用命换来的，是此刻方圆百里内唯一能让他们迅速“长肉”的东西。\n\n"
            "藤蔓会循着养分的浓度精准定位，将他们拖走。引导藤蔓精准收割。\n\n"
            "“爸……”周小禾喘息着，声音微弱得几乎听不见，“我是不是要死了？”\n\n"
            "“不会。”周也把手从兜里抽出来，没有带出凝胶。\n\n"
            "“我会一直带你走下去。”"
        ),
    )

    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    ok = asyncio.run(pipeline.final_safe_repair())

    assert ok is True
    ch6 = (tmp_path / "正文" / "第006章.md").read_text(encoding="utf-8")
    ch8 = (tmp_path / "正文" / "第008章.md").read_text(encoding="utf-8")
    ch9 = (tmp_path / "正文" / "第009章.md").read_text(encoding="utf-8")
    ch10 = (tmp_path / "正文" / "第010章.md").read_text(encoding="utf-8")

    assert "那里只有粗糙的皮肤和紧绷的肌肉" not in ch6
    assert "掌纹里那抹淡绿" in ch6
    assert "“禾苗1.0是安全的。”" not in ch8
    assert "装着逆转录酶的空试管" not in ch8
    assert "又把一只防水资料袋压在试管旁边" in ch9
    assert "逆转录酶没有起效" not in ch10
    assert "这是周也留下的最后一点保命糖分" in ch10
    assert "精准定位" not in ch10
    assert "精准收割" not in ch10
    assert "我们会死吗" in ch10
    assert "“我不知道。”" in ch10
    assert (tmp_path / ".aznovel" / "final_safe_repair" / "latest_report.md").exists()


def test_final_polish_applies_small_manuscript_patches(tmp_path) -> None:
    _write_test_chapter(
        tmp_path,
        7,
        "逃亡",
        (
            "周也没有接话，他拉起儿子，沿着水渠继续往远离城区的方向走。荒野求生不是电影里的浪漫，每一寸推进都在消耗卡路里，而卡路里必须数量闭环。半块饼干撑不过今晚，他必须找到食物，或者至少，找到一个能避开夜间追捕的掩体。\n\n"
            "“什么都没有。”男人痛苦地抓挠着头皮，“连张纸片都没留下。他是个疯子，他以为自己在创造神，结果造出了魔鬼，最后只能选择消失。不管是死是活，汪禾都不会再出现了。我们没救了。”\n\n"
            "绝望像冰冷的蛇，顺着周也的脊椎爬上来。他看着男人空洞的眼睛，知道那不是谎言。寻找源头的希望被生生掐断，只剩下一地灰烬。"
        ),
    )
    _write_test_chapter(
        tmp_path,
        8,
        "真相",
        (
            "汪禾只是掏出了一支没有标签的试管，里面残留着几滴浑浊的液体。\n\n"
            "汪禾沉默了。他低头看着手里的空试管，手指不受控制地摩挲着玻璃壁。\n\n"
            "这里是那个男人临死前提及的地方——植物生态研究所的地下核心区。"
        ),
    )
    _write_test_chapter(
        tmp_path,
        10,
        "末日口粮",
        "没有安全的地方。这颗星球已经变成了一个巨大的餐盘。他们能做的，只是做一道难以下咽的菜，在餐盘的边缘不断游走，躲避着刀叉的叉取。",
    )

    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    ok = asyncio.run(pipeline.final_polish())

    assert ok is True
    ch7 = (tmp_path / "正文" / "第007章.md").read_text(encoding="utf-8")
    ch8 = (tmp_path / "正文" / "第008章.md").read_text(encoding="utf-8")
    ch10 = (tmp_path / "正文" / "第010章.md").read_text(encoding="utf-8")

    assert "数量闭环" not in ch7
    assert "植物生态研究所地下核心区" in ch7
    assert "手里的空试管" not in ch8
    assert "手里的残液试管" in ch8
    assert "巨大的餐盘" not in ch10
    assert "始终难以下咽" in ch10
    assert (tmp_path / ".aznovel" / "final_polish" / "latest_report.md").exists()
