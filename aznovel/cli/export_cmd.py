"""Export book CLI command."""

from __future__ import annotations

from pathlib import Path

import typer

from aznovel.core.exporter import ExportError, export_book
from aznovel.storage import project_fs
from aznovel.utils.rich_ui import error, info, success


def _run_export_inner(
    root: Path,
    formats: str | list[str] | tuple[str, ...] | None = "epub",
    output: str | Path | None = None,
) -> bool:
    """Core export logic, callable from chat or CLI."""
    try:
        exported = export_book(root, formats=formats, output=output)
    except ExportError as exc:
        error(str(exc))
        return False

    success("全书导出完成！")
    for path in exported:
        try:
            shown = path.relative_to(root)
        except ValueError:
            shown = path
        info(f"  {shown}")
    return True


def run_export(
    formats: str = "epub",
    output: str | None = None,
) -> None:
    """CLI entry point for exporting the whole book."""
    root = project_fs.find_project_root()
    if root is None:
        error("未找到 AZNovel 项目。请先运行 'aznovel init'")
        raise typer.Exit(1)

    ok = _run_export_inner(root, formats=formats, output=output)
    if not ok:
        raise typer.Exit(1)
