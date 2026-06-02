from aznovel.core.context import build_writing_brief
from aznovel.models.contract import ChapterBrief, MasterSetting
from aznovel.models.project import ProjectState


def test_writing_brief_requires_direct_events_and_resource_closure() -> None:
    brief = ChapterBrief(
        chapter_number=5,
        title="异变",
        summary="结尾第一起公开攻击事件发生，农场主被禾苗吞噬。",
    )

    text = build_writing_brief(brief, MasterSetting(), ProjectState())

    assert "不要只用新闻推送、录像、回忆、传闻或他人口述替代现场事件" in text
    assert "资源约束必须数量闭环" in text
