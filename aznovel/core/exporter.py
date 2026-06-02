"""Book export helpers for AZNovel projects."""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from aznovel.storage import project_fs
from aznovel.storage.state_store import StateStore
from aznovel.utils.text import extract_chapter_number

SUPPORTED_EXPORT_FORMATS = ("epub", "pdf", "mobi", "docx")


class ExportError(RuntimeError):
    """Raised when a book export cannot be completed."""


@dataclass(frozen=True)
class BookChapter:
    """A chapter prepared for export."""

    number: int
    title: str
    body: str
    path: Path


@dataclass(frozen=True)
class BookContent:
    """A complete book prepared for export."""

    title: str
    author: str
    chapters: list[BookChapter]


def normalize_formats(formats: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize user-supplied export formats."""
    if formats is None:
        raw_items = ["epub"]
    elif isinstance(formats, str):
        raw_items = [item for item in re.split(r"[\s,，、/]+", formats.lower()) if item]
    else:
        raw_items = []
        for fmt in formats:
            raw_items.extend(item for item in re.split(r"[\s,，、/]+", str(fmt).lower()) if item)

    aliases = {
        "all": "all",
        "全部": "all",
        "所有": "all",
        "epub": "epub",
        "pdf": "pdf",
        "mobi": "mobi",
        "kindle": "mobi",
        "docx": "docx",
        "word": "docx",
    }

    normalized: list[str] = []
    for item in raw_items:
        fmt = aliases.get(item)
        if fmt is None:
            raise ExportError(f"不支持的导出格式: {item}。支持: epub, pdf, mobi, docx")
        if fmt == "all":
            for supported in SUPPORTED_EXPORT_FORMATS:
                if supported not in normalized:
                    normalized.append(supported)
            continue
        if fmt not in normalized:
            normalized.append(fmt)

    if not normalized:
        normalized.append("epub")
    return normalized


def load_book(root: Path) -> BookContent:
    """Load all written chapters from an AZNovel project."""
    paths = project_fs.project_paths(root)
    chapters_dir = paths["chapters_dir"]
    if not chapters_dir.exists():
        raise ExportError("还没有正文目录，无法导出全书。")

    chapter_files: list[tuple[int, Path]] = []
    for path in chapters_dir.glob("第*章.md"):
        number = extract_chapter_number(path.name)
        if number is not None:
            chapter_files.append((number, path))

    if not chapter_files:
        raise ExportError("还没有任何章节，无法导出全书。")

    chapter_files.sort(key=lambda item: item[0])
    chapters = [
        _parse_chapter(path.read_text(encoding="utf-8"), number, path)
        for number, path in chapter_files
    ]

    state = StateStore(root).load()
    title = state.project_info.title.strip() or root.name or "未命名小说"
    author = state.project_info.author.strip()
    return BookContent(title=title, author=author, chapters=chapters)


def export_book(
    root: Path,
    formats: str | list[str] | tuple[str, ...] | None = "epub",
    output: str | Path | None = None,
) -> list[Path]:
    """Export the whole book to one file per requested format."""
    book = load_book(root)
    normalized = normalize_formats(formats)
    output_paths = _resolve_output_paths(root, book, normalized, output)

    exported: list[Path] = []
    for fmt in normalized:
        path = output_paths[fmt]
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "epub":
            export_epub(book, path)
        elif fmt == "docx":
            export_docx(book, path)
        elif fmt == "pdf":
            export_pdf(book, path)
        elif fmt == "mobi":
            export_mobi(book, path)
        else:
            raise ExportError(f"不支持的导出格式: {fmt}")
        exported.append(path)
    return exported


def export_epub(book: BookContent, output_path: Path) -> None:
    """Write the book as a single EPUB file."""
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with zipfile.ZipFile(output_path, "w") as zf:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        zf.writestr(mimetype, "application/epub+zip")
        zf.writestr("META-INF/container.xml", _epub_container_xml())
        zf.writestr("OEBPS/styles.css", _epub_css())
        zf.writestr("OEBPS/nav.xhtml", _epub_nav_xhtml(book))
        zf.writestr("OEBPS/content.opf", _epub_opf_xml(book, book_id, modified))
        for chapter in book.chapters:
            zf.writestr(
                f"OEBPS/chapters/chapter_{chapter.number:03d}.xhtml",
                _epub_chapter_xhtml(chapter, book.title),
            )


def export_docx(book: BookContent, output_path: Path) -> None:
    """Write the book as a single DOCX file."""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _docx_content_types_xml())
        zf.writestr("_rels/.rels", _docx_root_rels_xml())
        zf.writestr("docProps/core.xml", _docx_core_xml(book))
        zf.writestr("docProps/app.xml", _docx_app_xml())
        zf.writestr("word/styles.xml", _docx_styles_xml())
        zf.writestr("word/document.xml", _docx_document_xml(book))


def export_pdf(book: BookContent, output_path: Path) -> None:
    """Write the book as a single PDF file."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise ExportError("PDF 导出需要 reportlab。请先运行 `pip install reportlab`。") from exc

    font_name = "STSong-Light"
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    except Exception as exc:  # pragma: no cover - depends on reportlab internals
        raise ExportError(f"无法加载 PDF 中文字体 {font_name}: {exc}") from exc

    page_width, page_height = A4
    margin = 54
    body_size = 11.5
    body_leading = 19
    chapter_size = 16
    title_size = 22

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    pdf.setTitle(book.title)
    if book.author:
        pdf.setAuthor(book.author)

    page_number = 1
    y = page_height - margin

    def finish_page() -> None:
        nonlocal page_number
        pdf.setFont(font_name, 8)
        pdf.drawCentredString(page_width / 2, 28, str(page_number))
        pdf.showPage()
        page_number += 1

    def ensure_space(required: float) -> None:
        nonlocal y
        if y - required < margin:
            finish_page()
            y = page_height - margin

    def draw_wrapped(text: str, size: float, leading: float, indent: float = 0) -> None:
        nonlocal y
        max_width = page_width - margin * 2 - indent
        for line in _wrap_pdf_text(text, font_name, size, max_width, pdfmetrics):
            ensure_space(leading)
            pdf.setFont(font_name, size)
            pdf.drawString(margin + indent, y, line)
            y -= leading

    y = page_height * 0.62
    pdf.setFont(font_name, title_size)
    for line in _wrap_pdf_text(book.title, font_name, title_size, page_width - margin * 2, pdfmetrics):
        pdf.drawCentredString(page_width / 2, y, line)
        y -= 34
    if book.author:
        y -= 10
        pdf.setFont(font_name, 12)
        pdf.drawCentredString(page_width / 2, y, book.author)
    finish_page()

    for chapter in book.chapters:
        y = page_height - margin
        draw_wrapped(chapter.title, chapter_size, 24)
        y -= 12
        for paragraph in _paragraphs(chapter.body):
            if not paragraph:
                y -= body_leading
                continue
            draw_wrapped(paragraph, body_size, body_leading)
            y -= 6
        finish_page()

    pdf.save()


def export_mobi(book: BookContent, output_path: Path) -> None:
    """Write the book as a single MOBI file using an installed converter."""
    ebook_convert = shutil.which("ebook-convert")
    kindlegen = shutil.which("kindlegen")
    if not ebook_convert and not kindlegen:
        raise ExportError(
            "MOBI 导出需要安装 Calibre 的 `ebook-convert` 或 Amazon `kindlegen`。"
        )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        epub_path = tmp_dir / "book.epub"
        export_epub(book, epub_path)

        if ebook_convert:
            result = subprocess.run(
                [ebook_convert, str(epub_path), str(output_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise ExportError(_converter_error("ebook-convert", result))
            return

        temp_output = tmp_dir / output_path.name
        result = subprocess.run(
            [kindlegen, str(epub_path), "-o", output_path.name],
            cwd=str(tmp_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ExportError(_converter_error("kindlegen", result))
        if not temp_output.exists():
            raise ExportError("kindlegen 未生成 MOBI 文件。")
        shutil.move(str(temp_output), str(output_path))


def _parse_chapter(text: str, number: int, path: Path) -> BookChapter:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\ufeff\n")
    lines = normalized.split("\n")
    title = f"第{number}章"
    body_start = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if match:
            title = match.group(1).strip()
            body_start = index + 1
        break
    body = "\n".join(lines[body_start:]).strip()
    return BookChapter(number=number, title=title, body=body, path=path)


def _paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n+", normalized):
        clean = block.strip()
        if not clean:
            continue
        clean = re.sub(r"^#{1,6}\s+", "", clean)
        paragraphs.append(clean)
    return paragraphs


def _resolve_output_paths(
    root: Path,
    book: BookContent,
    formats: list[str],
    output: str | Path | None,
) -> dict[str, Path]:
    if output is None:
        output_dir = root / "导出"
        explicit_file: Path | None = None
    else:
        output_path = Path(output).expanduser()
        if not output_path.is_absolute():
            output_path = root / output_path
        if len(formats) == 1 and output_path.suffix:
            explicit_file = output_path
            output_dir = output_path.parent
        elif len(formats) > 1 and output_path.suffix:
            raise ExportError("导出多个格式时，--output 请指定目录，不要指定单个文件名。")
        else:
            explicit_file = None
            output_dir = output_path

    if explicit_file is not None:
        fmt = formats[0]
        if explicit_file.suffix.lower() != f".{fmt}":
            explicit_file = explicit_file.with_suffix(f".{fmt}")
        return {fmt: explicit_file}

    stem = _safe_filename(book.title) or "未命名小说"
    return {fmt: output_dir / f"{stem}.{fmt}" for fmt in formats}


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80].strip(" .")


def _epub_container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _epub_css() -> str:
    return """body { font-family: serif; line-height: 1.75; margin: 5%; }
h1 { font-size: 1.6em; margin: 1.2em 0; text-align: center; }
p { margin: 0 0 1em 0; text-indent: 2em; }
nav ol { line-height: 1.8; }
"""


def _epub_nav_xhtml(book: BookContent) -> str:
    items = "\n".join(
        f'      <li><a href="chapters/chapter_{chapter.number:03d}.xhtml">{html.escape(chapter.title)}</a></li>'
        for chapter in book.chapters
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">
  <head>
    <title>{html.escape(book.title)} 目录</title>
    <link rel="stylesheet" type="text/css" href="styles.css"/>
  </head>
  <body>
    <nav epub:type="toc" id="toc">
      <h1>目录</h1>
      <ol>
{items}
      </ol>
    </nav>
  </body>
</html>
"""


def _epub_opf_xml(book: BookContent, book_id: str, modified: str) -> str:
    manifest = [
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="style" href="styles.css" media-type="text/css"/>',
    ]
    spine = []
    for chapter in book.chapters:
        item_id = f"chapter_{chapter.number:03d}"
        manifest.append(
            f'    <item id="{item_id}" href="chapters/{item_id}.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'    <itemref idref="{item_id}"/>')

    creator = (
        f"    <dc:creator>{xml_escape(book.author)}</dc:creator>\n"
        if book.author
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="bookid" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{xml_escape(book_id)}</dc:identifier>
    <dc:title>{xml_escape(book.title)}</dc:title>
{creator}    <dc:language>zh-CN</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
{chr(10).join(manifest)}
  </manifest>
  <spine>
{chr(10).join(spine)}
  </spine>
</package>
"""


def _epub_chapter_xhtml(chapter: BookChapter, book_title: str) -> str:
    paragraphs = "\n".join(
        f"      <p>{html.escape(paragraph).replace(chr(10), '<br/>')}</p>"
        for paragraph in _paragraphs(chapter.body)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">
  <head>
    <title>{html.escape(chapter.title)} - {html.escape(book_title)}</title>
    <link rel="stylesheet" type="text/css" href="../styles.css"/>
  </head>
  <body>
    <section epub:type="chapter">
      <h1>{html.escape(chapter.title)}</h1>
{paragraphs}
    </section>
  </body>
</html>
"""


def _docx_content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""


def _docx_root_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def _docx_core_xml(book: BookContent) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    creator = xml_escape(book.author or "AZNovel")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{xml_escape(book.title)}</dc:title>
  <dc:creator>{creator}</dc:creator>
  <cp:lastModifiedBy>AZNovel</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>
"""


def _docx_app_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>AZNovel</Application>
</Properties>
"""


def _docx_styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体"/><w:sz w:val="24"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:jc w:val="center"/><w:spacing w:after="480"/></w:pPr>
    <w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="黑体"/><w:b/><w:sz w:val="44"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:keepNext/><w:jc w:val="center"/><w:spacing w:before="360" w:after="240"/></w:pPr>
    <w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="黑体"/><w:b/><w:sz w:val="32"/></w:rPr>
  </w:style>
</w:styles>
"""


def _docx_document_xml(book: BookContent) -> str:
    parts = [_docx_paragraph(book.title, "Title", align="center")]
    if book.author:
        parts.append(_docx_paragraph(book.author, None, align="center"))

    for chapter in book.chapters:
        parts.append(_docx_paragraph(chapter.title, "Heading1", align="center"))
        for paragraph in _paragraphs(chapter.body):
            parts.append(_docx_paragraph(paragraph))

    body = "\n".join(parts)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
{body}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""


def _docx_paragraph(text: str, style: str | None = None, align: str | None = None) -> str:
    ppr_parts = []
    if style:
        ppr_parts.append(f'<w:pStyle w:val="{style}"/>')
    if align:
        ppr_parts.append(f'<w:jc w:val="{align}"/>')
    if style is None and align is None:
        ppr_parts.append('<w:spacing w:line="420" w:lineRule="auto" w:after="120"/>')
        ppr_parts.append('<w:ind w:firstLineChars="200"/>')
    ppr = f"<w:pPr>{''.join(ppr_parts)}</w:pPr>" if ppr_parts else ""
    return f"    <w:p>{ppr}{_docx_runs(text)}</w:p>"


def _docx_runs(text: str) -> str:
    segments = text.split("\n")
    runs = []
    for index, segment in enumerate(segments):
        if index:
            runs.append("<w:r><w:br/></w:r>")
        runs.append(f"<w:r><w:t{_xml_space(segment)}>{xml_escape(segment)}</w:t></w:r>")
    return "".join(runs)


def _xml_space(text: str) -> str:
    if text[:1].isspace() or text[-1:].isspace():
        return ' xml:space="preserve"'
    return ""


def _wrap_pdf_text(text: str, font_name: str, size: float, max_width: float, pdfmetrics) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            if current:
                lines.append(current)
                current = ""
            continue
        candidate = current + char
        if current and pdfmetrics.stringWidth(candidate, font_name, size) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _converter_error(name: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        detail = detail[-1200:]
        return f"{name} 转换失败：\n{detail}"
    return f"{name} 转换失败，退出码 {result.returncode}。"
