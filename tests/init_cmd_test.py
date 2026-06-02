from aznovel.cli.init_cmd import _looks_like_init_drafting_request


def test_init_drafting_guard_detects_continue() -> None:
    assert _looks_like_init_drafting_request("继续")
    assert _looks_like_init_drafting_request("写下一章")


def test_init_drafting_guard_detects_chapter_write() -> None:
    assert _looks_like_init_drafting_request("写第12章")
    assert _looks_like_init_drafting_request("续写第三章")


def test_init_drafting_guard_allows_project_brainstorming() -> None:
    assert not _looks_like_init_drafting_request("我想写一个末日粮食题材的故事")
