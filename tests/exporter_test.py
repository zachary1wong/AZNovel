import zipfile

from aznovel.core.exporter import export_book, load_book, normalize_formats
from aznovel.models.project import ProjectInfo, ProjectState
from aznovel.storage.state_store import StateStore


def _write_sample_book(root):
    StateStore(root).save(
        ProjectState(project_info=ProjectInfo(title="测试小说", author="测试作者"))
    )
    (root / "正文" / "第002章.md").write_text(
        "# 第二章 风声\n\n他推开门。\n\n风从巷口灌进来。",
        encoding="utf-8",
    )
    (root / "正文" / "第001章.md").write_text(
        "# 第一章 雨夜\n\n雨落在旧街。\n\n她没有回头。",
        encoding="utf-8",
    )


def test_normalize_formats_supports_all_and_aliases():
    assert normalize_formats("all") == ["epub", "pdf", "mobi", "docx"]
    assert normalize_formats("epub, word/kindle") == ["epub", "docx", "mobi"]


def test_load_book_sorts_chapters_by_number(tmp_project):
    _write_sample_book(tmp_project)

    book = load_book(tmp_project)

    assert book.title == "测试小说"
    assert [chapter.number for chapter in book.chapters] == [1, 2]
    assert book.chapters[0].title == "第一章 雨夜"


def test_export_book_writes_single_epub_and_docx_files(tmp_project):
    _write_sample_book(tmp_project)

    exported = export_book(tmp_project, ["epub", "docx"])

    assert exported == [
        tmp_project / "导出" / "测试小说.epub",
        tmp_project / "导出" / "测试小说.docx",
    ]
    for path in exported:
        assert path.exists()

    with zipfile.ZipFile(exported[0]) as epub:
        assert epub.read("mimetype") == b"application/epub+zip"
        nav = epub.read("OEBPS/nav.xhtml").decode("utf-8")
        chapter = epub.read("OEBPS/chapters/chapter_001.xhtml").decode("utf-8")
    assert "第一章 雨夜" in nav
    assert "雨落在旧街" in chapter

    with zipfile.ZipFile(exported[1]) as docx:
        document = docx.read("word/document.xml").decode("utf-8")
        styles = docx.read("word/styles.xml").decode("utf-8")
    assert "测试小说" in document
    assert "风从巷口灌进来" in document
    assert '<w:style w:type="paragraph" w:styleId="Title">' in styles
    assert '<w:pPr><w:jc w:val="center"/><w:spacing w:after="480"/></w:pPr>' in styles
    assert 'w:eastAsia="黑体"' in styles
    assert '<w:style w:type="paragraph" w:styleId="Heading1">' in styles
    assert '<w:keepNext/><w:jc w:val="center"/><w:spacing w:before="360" w:after="240"/>' in styles
    assert '<w:pStyle w:val="Title"/><w:jc w:val="center"/>' in document
    assert '<w:pStyle w:val="Heading1"/><w:jc w:val="center"/>' in document
