import asyncio

from aznovel.core.renamer import rename_character
from aznovel.models.project import EntityRecord, ProjectState
from aznovel.storage import project_fs
from aznovel.storage.state_store import StateStore


def _init_project(root):
    project_fs.ensure_project_dirs(root)
    state = ProjectState()
    state.project_info.title = "测试小说"
    state.protagonist.name = "周小禾"
    state.entities = [
        EntityRecord(
            name="周小禾",
            type="character",
            aliases=["小禾", "禾禾"],
            first_appearance=1,
        )
    ]
    StateStore(root).save(state)


def test_rename_character_updates_name_variants_without_touching_unrelated_terms(tmp_path) -> None:
    _init_project(tmp_path)
    chapter_path = tmp_path / "正文" / "第001章.md"
    chapter_path.write_text(
        "# 第一章\n\n周小禾把碗推开。小禾低声说，禾禾不想吃禾苗。\n",
        encoding="utf-8",
    )
    (tmp_path / "大纲" / "总纲.md").write_text(
        "周小禾在第一章拒绝禾苗。",
        encoding="utf-8",
    )

    ok = asyncio.run(
        rename_character(
            None,
            tmp_path,
            old_name="周小禾",
            new_name="周小森",
        )
    )

    assert ok is True
    chapter = chapter_path.read_text(encoding="utf-8")
    assert "周小森" in chapter
    assert "小森" in chapter
    assert "森森" in chapter
    assert "周小禾" not in chapter
    assert "小禾" not in chapter
    assert "禾禾" not in chapter
    assert "禾苗" in chapter

    outline = (tmp_path / "大纲" / "总纲.md").read_text(encoding="utf-8")
    assert "周小森" in outline
    assert "周小禾" not in outline

    state_text = (tmp_path / ".aznovel" / "state.json").read_text(encoding="utf-8")
    assert "周小森" in state_text
    assert "小森" in state_text
    assert "森森" in state_text
    assert "周小禾" not in state_text


def test_rename_character_dry_run_writes_candidate_without_overwriting(tmp_path) -> None:
    _init_project(tmp_path)
    chapter_path = tmp_path / "正文" / "第001章.md"
    chapter_path.write_text("# 第一章\n\n周小禾看着小禾的旧校牌。\n", encoding="utf-8")

    ok = asyncio.run(
        rename_character(
            None,
            tmp_path,
            old_name="周小禾",
            new_name="周小森",
            dry_run=True,
        )
    )

    assert ok is True
    assert "周小禾" in chapter_path.read_text(encoding="utf-8")

    after_files = list((tmp_path / ".aznovel" / "renames").glob("*/after/正文/第001章.md"))
    assert after_files
    candidate = after_files[-1].read_text(encoding="utf-8")
    assert "周小森" in candidate
    assert "小森" in candidate
    assert "周小禾" not in candidate


def test_rename_character_updates_surname_title_forms(tmp_path) -> None:
    _init_project(tmp_path)
    chapter_path = tmp_path / "正文" / "第001章.md"
    chapter_path.write_text(
        "# 第一章\n\n汪禾教授看向镜头。记者问汪教授，汪禾是否后悔研发禾苗。\n",
        encoding="utf-8",
    )

    ok = asyncio.run(
        rename_character(
            None,
            tmp_path,
            old_name="汪禾",
            new_name="王希昂",
        )
    )

    assert ok is True
    chapter = chapter_path.read_text(encoding="utf-8")
    assert "王希昂教授" in chapter
    assert "王教授" in chapter
    assert "王希昂是否后悔" in chapter
    assert "汪禾" not in chapter
    assert "汪教授" not in chapter
    assert "禾苗" in chapter
