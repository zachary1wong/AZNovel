from aznovel.core.review_engine import ReviewEngine
from aznovel.models.contract import ReviewContract


class FailingProvider:
    async def chat_json(self, *args, **kwargs):
        raise ValueError("bad json")


class StaticProvider:
    def __init__(self, payload):
        self.payload = payload

    async def chat_json(self, *args, **kwargs):
        return self.payload


async def test_review_failure_blocks_commit() -> None:
    engine = ReviewEngine(FailingProvider())

    result = await engine.review_chapter(
        "正文",
        ReviewContract(chapter_number=4),
    )

    assert result.passed is False
    assert result.blocking_count == 1
    assert result.issues[0].category == "review_engine"


async def test_review_filters_self_contradictory_outline_entity_issue() -> None:
    engine = ReviewEngine(
        StaticProvider(
            {
                "issues": [
                    {
                        "severity": "critical",
                        "category": "outline_compliance",
                        "location": "全文",
                        "description": "大纲要求角色名为‘周也’，但正文全篇将其写为‘周也’，角色名称偏离。",
                        "evidence": "周也推着箱子回家。",
                        "blocking": True,
                    }
                ],
                "summary": "存在大纲问题。",
            }
        )
    )

    result = await engine.review_chapter(
        "周也推着箱子回家，周小禾坐在桌边。",
        ReviewContract(
            chapter_number=4,
            known_entities=["周也", "周小禾"],
            outline_summary="周也发现禾苗2.0异常，周小禾食用后症状加剧。",
        ),
    )

    assert result.passed is True
    assert result.blocking_count == 0
    assert result.issues == []


async def test_review_filters_false_role_swap_from_incomplete_entity_evidence() -> None:
    engine = ReviewEngine(
        StaticProvider(
            {
                "issues": [
                    {
                        "severity": "high",
                        "category": "setting",
                        "location": "第7段",
                        "description": "人物名称与已知实体列表不符。正文使用'周也'作为主角，但已知实体列表中配送员角色名为'周小禾'，存在人物设定矛盾。",
                        "evidence": "正文：'周也按下收音机的开关'；已知实体：'周小禾, 禾苗'",
                        "blocking": True,
                    },
                    {
                        "severity": "high",
                        "category": "setting",
                        "location": "第11段",
                        "description": "人物关系设定矛盾。正文设定'周也'为配送员，'周小禾'为其儿子；但已知实体列表中'周小禾'与'禾苗'并列出现，暗示周小禾应为配送员主角，而非儿子角色。",
                        "evidence": "正文：'他想起了家里的儿子周小禾'",
                        "blocking": True,
                    },
                ],
                "summary": "存在人物错位。",
            }
        )
    )

    result = await engine.review_chapter(
        "周也按下收音机的开关。他想起了家里的儿子周小禾。",
        ReviewContract(
            chapter_number=4,
            known_entities=["周也", "周小禾", "禾苗"],
            established_rules=["主角是周也，身份/状态：失业半年的前财务从业者，当前目标：保护12岁儿子周小禾"],
            outline_summary="周也配送时发现2.0气息奇怪。儿子周小禾食用2.0后症状加重。",
        ),
    )

    assert result.passed is True
    assert result.blocking_count == 0
    assert result.issues == []
