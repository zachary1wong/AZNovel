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


def test_repair_strategy_notes_handle_indirect_events_and_resource_gaps(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "大纲要求结尾第一起公开攻击事件发生，农场主被禾苗吞噬。"
        "正文实际是一条紧急新闻推送和监控录像。"
        "周也靠零活维生，早餐时周小禾吃了两份禾苗2.0并要求更多，配给制下存量不可信。"
    )

    instruction = pipeline._build_polish_instruction(
        chapter_text="正文",
        review_report=report,
        chapter=5,
        outline={"summary": "第一起公开攻击事件发生，农场主被禾苗吞噬。"},
        known_entities=["周也", "周小禾"],
    )

    assert "自动诊断修复策略" in instruction
    assert "不能只通过新闻、手机推送、录像、回忆或他人口述完成" in instruction
    assert "资源稀缺或配给制冲突必须用数量闭环解决" in instruction


def test_repair_strategy_notes_handle_food_lure_contradiction(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "汪禾被设定为饥饿的幸存者，但正文为解释其被攻击的原因，"
        "强行设定他刚刚进食过压缩饼干成为优质食物源，"
        "这与末日配给制下的生存常态产生逻辑冲突。"
    )

    instruction = pipeline._build_micro_evidence_patch_instruction(
        evidence=(
            "汪禾的牺牲，不仅是因为他制造了气味干扰，更因为他是一个刚刚进食过压缩饼干、"
            "体内重新获得了热量和营养的“优质食物源”。那半块饼干的代价，就是让他成为了藤蔓首选的吞噬目标。"
        ),
        review_report=report,
        outline={"summary": "汪禾牺牲自己引开禾苗，周也带儿子和研究资料逃离。"},
    )

    assert "压缩饼干/优质食物源" in instruction
    assert "收回到正文已有的化学诱饵" in instruction
    assert "如果问题是错误因果或强行解释" in instruction


def test_repair_strategy_notes_handle_mumbling_and_abstract_thinking(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "大纲要求儿子夜里眼睛泛微光喃喃自语，但正文写成代码式术语：碳基、载体、适配度。"
        "大纲要求周也惊恐发现禾苗在思考，但正文通过抽象主观论述和运算解释完成，缺少直观场景。"
    )

    instruction = pipeline._build_local_patch_instruction(
        chapter_text="正文",
        review_report=report,
        chapter=5,
        outline={"summary": "周也儿子夜里眼睛泛微光喃喃自语，周也惊恐发现禾苗在思考。"},
        known_entities=["周也", "周小禾"],
    )

    assert "喃喃自语被写成代码式术语" in instruction
    assert "改为含混、破碎、低声的人类语句" in instruction
    assert "改为可被看见/听见的现场证据" in instruction


def test_repair_strategy_notes_handle_accountant_tactical_ooc(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "周也的设定为失业半年的前财务从业者，但文中表现出极强战术素养，"
        "如战略储备、精确制导的屠宰、战术规避，与人物设定严重割裂。"
    )

    instruction = pipeline._build_local_patch_instruction(
        chapter_text="正文",
        review_report=report,
        chapter=10,
        outline={"summary": "周也带儿子继续逃亡，世界面目全非。"},
        known_entities=["周也", "周小禾"],
    )

    assert "前财务从业者被写成军事/战术专家" in instruction
    assert "删除战略、战术、精确制导" in instruction
    assert "重新核对一笔坏账" in instruction


def test_repair_strategy_notes_handle_swallowed_not_half_alive(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "大纲要求农场主被禾苗吞噬，但正文写成赵金标没有死，"
        "还能主动攻击周也，未被吞噬消失，存在偏离。"
    )

    instruction = pipeline._build_polish_instruction(
        chapter_text="正文",
        review_report=report,
        chapter=5,
        outline={"summary": "结尾第一起公开攻击事件发生，农场主被禾苗吞噬。"},
        known_entities=["周也"],
    )

    assert "必须让该角色在现场被吸收、消化、消失或只剩衣物/骨骼残留" in instruction
    assert "不要改成半活怪物、宿主反扑或战斗场面" in instruction


def test_repair_strategy_notes_handle_infection_progression(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "周也手背青紫脉络泛荧光的变异程度与禾苗同化逻辑冲突，"
        "若变异至此应丧失行动能力，不可能自由行动。"
    )

    instruction = pipeline._build_local_patch_instruction(
        chapter_text="正文",
        review_report=report,
        chapter=5,
        outline={"summary": "周也发现禾苗在思考。"},
        known_entities=["周也"],
    )

    assert "把主角症状降级为早期、局部、间歇性反应" in instruction
    assert "不能写到与被吞噬者相同的全身同化程度" in instruction


def test_repair_strategy_notes_handle_premature_child_reveal(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "周小禾表现出明显的被同化症状，瞳孔发光、与植物共鸣、无恐惧，"
        "与大纲结尾才发现儿子被标记的节奏冲突，提前暴露异变状态。"
    )

    instruction = pipeline._build_local_patch_instruction(
        chapter_text="正文",
        review_report=report,
        chapter=6,
        outline={"summary": "结尾周也发现儿子被标记。"},
        known_entities=["周也", "周小禾"],
    )

    assert "儿子的异变/被标记暴露过早" in instruction
    assert "降级为可疑但未定性的异常线索" in instruction


def test_repair_strategy_notes_handle_chapter_overrun_and_serum_timing(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "第8章大纲要求结尾禾苗包围实验室，但正文写成禾苗完全涌入并吞噬，"
        "汪禾牺牲自己，周也逃离并给儿子注射解药。"
        "汪禾前文说解药需要一个月也许两个月，血清分离还需要十五分钟，"
        "后文却立刻用抗性因子合成淡蓝色注射剂。"
    )

    instruction = pipeline._build_local_patch_instruction(
        chapter_text="正文",
        review_report=report,
        chapter=8,
        outline={"summary": "汪禾正研究解药但需时间。结尾禾苗包围实验室。"},
        known_entities=["周也", "周小禾", "汪禾"],
    )

    assert "章节越界" in instruction
    assert "收回到大纲指定的悬念点" in instruction
    assert "不能让刚采集的血样在几分钟内合成新药" in instruction


def test_tail_repair_detects_chapter_overrun_boundary(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = (
        "第8章大纲要求结尾禾苗包围实验室，但正文提前写出汪禾牺牲、"
        "周也逃离、注射解药和药效见效。"
    )
    chapter_text = (
        "汪禾说血清分离还需要十五分钟。\n\n"
        "话音未落，一声巨响从门外传来。那扇厚重的金属门开始变形。\n\n"
        "周也抱着儿子逃离，针头刺入周小禾的手臂。"
    )

    assert pipeline._is_chapter_overrun_report(report) is True
    start = pipeline._find_tail_repair_start(chapter_text, report)
    assert start == chapter_text.index("话音未落")


def test_tail_repair_boundary_can_include_bad_door_time_estimate(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = "门能挡住三小时四小时，但十五分钟内就被攻破，防御时间矛盾。"
    chapter_text = (
        "汪禾说还需要时间。\n\n"
        "可以，但撑不了多久。汪禾走向控制面板，这道门能挡住它们三小时。也许四小时。\n\n"
        "话音未落，一声巨响从门外传来。"
    )

    start = pipeline._find_tail_repair_start(chapter_text, report)
    assert start == chapter_text.index("可以，但撑不了多久。")


def test_tail_repair_boundary_starts_at_breach_when_only_breach_overruns(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    report = "大纲要求结尾禾苗包围实验室，但正文写成气密门彻底倒塌，藤蔓漫过门槛并探到操作台。"
    chapter_text = (
        "门缝里的绿光越来越亮，门板发出痛苦的呻吟。\n\n"
        "气密门彻底倒塌。\n\n"
        "数不清的藤蔓像决堤的洪水般漫过门槛，一根纤细的藤蔓从操作台边缘探出。"
    )

    instruction = pipeline._build_tail_repair_instruction(
        prefix=chapter_text[: chapter_text.index("气密门彻底倒塌")].strip(),
        tail=chapter_text[chapter_text.index("气密门彻底倒塌"):],
        review_report=report,
        chapter=8,
        outline={"summary": "结尾禾苗包围实验室。"},
        known_entities=["周也", "周小禾", "汪禾"],
    )

    start = pipeline._find_tail_repair_start(chapter_text, report)
    assert start == chapter_text.index("气密门彻底倒塌")
    assert "包围不等于攻破" in instruction
    assert "禁止写气密门倒塌" in instruction


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
        "汪禾的牺牲，不仅是因为他制造了气味干扰，更因为他是一个刚刚进食过压缩饼干、"
        "体内重新获得了热量和营养的“优质食物源”。那半块饼干的代价，就是让他成为了藤蔓首选的吞噬目标。"
    )
    report = (
        "### 🟠 问题 1 [BLOCKING]\n"
        "- **类别**: logic\n"
        "- **描述**: 刚进食压缩饼干成为优质食物源，与配给制生存常态逻辑冲突。\n"
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


def test_deterministic_review_patch_removes_food_lure_contradiction(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    evidence = (
        "汪禾的牺牲，不仅是因为他制造了气味干扰，更因为他是一个刚刚进食过压缩饼干、"
        "体内重新获得了热量和营养的“优质食物源”。那半块饼干的代价，就是让他成为了藤蔓首选的吞噬目标。"
    )
    report = (
        "### 🔴 问题 1 [BLOCKING]\n"
        "- **类别**: stale_blocking_evidence\n"
        "- **描述**: 旧阻断证据仍保留，压缩饼干成为优质食物源与配给制生存常态逻辑冲突。\n"
        f"- **证据**: > {evidence}"
    )

    text, applied = pipeline._apply_deterministic_review_patches(
        f"前文。\n\n{evidence}\n\n后文。",
        report,
    )

    assert applied == 1
    assert evidence not in text
    assert "压缩饼干" not in text
    assert "营养液、福尔马林和血" in text


def test_deterministic_review_patch_adds_missing_research_material(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    original = "急救包里的逆转录酶硌着他的肋骨，那是汪禾用命换来的七分之一概率。"
    report = (
        "### 🔴 问题 1 [BLOCKING]\n"
        "- **类别**: outline_object_guard\n"
        "- **描述**: 候选稿遗漏大纲要求的关键道具：研究资料。\n"
        "- **证据**: > 大纲要求“研究资料”出现在本章逃离链条中。"
    )

    text, applied = pipeline._apply_deterministic_review_patches(original, report)

    assert applied == 1
    assert "防水资料袋" in text
    assert "实验记录、配方页和数据芯片" in text


def test_deterministic_review_patch_removes_accountant_tactical_ooc(tmp_path) -> None:
    pipeline = WritingPipeline(DummyProvider(), tmp_path)
    paragraph = (
        "聚居地不是避难所，而是养殖场。那些高墙和铁丝网，不是为了把禾苗挡在外面，"
        "而是为了把人类圈在里面。当禾苗需要进食时，标记者就会发作，引导藤蔓精准收割。"
        "人类在恐惧中互相依偎，以为只要熬过冬天就能等来救援，却不知道自己只是被圈养在笼中的肉畜，"
        "每一寸脂肪的积累，都只是为了最终的屠宰。"
    )
    report = (
        "### 🔴 问题 1 [BLOCKING]\n"
        "- **类别**: setting\n"
        "- **描述**: 周也是前财务从业者，但文中出现战略储备、精确制导的屠宰、战术规避，战术素养严重割裂。"
    )

    text, applied = pipeline._apply_deterministic_review_patches(paragraph, report)

    assert applied >= 1
    assert "精准收割" not in text
    assert "错账" in text
    assert "亏空" in text


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
        "汪禾的牺牲，不仅是因为他制造了气味干扰，更因为他是一个刚刚进食过压缩饼干、"
        "体内重新获得了热量和营养的“优质食物源”。那半块饼干的代价，就是让他成为了藤蔓首选的吞噬目标。"
    )
    previous_report = (
        "### 🟠 问题 1 [BLOCKING]\n"
        "- **类别**: logic\n"
        "- **描述**: 刚刚进食压缩饼干成为优质食物源，与配给制生存常态逻辑冲突。\n"
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
