"""Status CLI command."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from aznovel.storage import project_fs
from aznovel.storage.state_store import StateStore
from aznovel.utils.rich_ui import console, error
from aznovel.utils.text import count_chinese_chars


def _show_status(root: Path) -> None:
    """Show project status (callable from chat or CLI)."""
    paths = project_fs.project_paths(root)
    store = StateStore(root)
    state = store.load()

    console.print(f"\n[bold]{state.project_info.title or '未命名项目'}[/]")
    console.print(f"题材: {state.project_info.genre or '未设置'}")
    console.print(f"目标章数: {state.project_info.target_chapters}")

    chapters_dir = paths["chapters_dir"]
    existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []
    total_words = 0
    for f in existing:
        total_words += count_chinese_chars(f.read_text(encoding="utf-8"))

    console.print(f"\n[bold]写作进度[/]")
    console.print(f"  已完成章节: {len(existing)}")
    console.print(f"  总字数: {total_words:,}")
    console.print(f"  当前卷: {state.progress.current_volume}")

    if state.protagonist.name:
        console.print(f"\n[bold]主角: {state.protagonist.name}[/]")
        if state.protagonist.cultivation:
            console.print(f"  境界: {state.protagonist.cultivation}")
        if state.protagonist.current_goal:
            console.print(f"  目标: {state.protagonist.current_goal}")

    if state.entities:
        console.print(f"\n[bold]已记录实体: {len(state.entities)}[/]")
        table = Table(show_header=True)
        table.add_column("名称", style="bold")
        table.add_column("类型")
        table.add_column("首次出现")
        for ent in state.entities[:10]:
            table.add_row(ent.name, ent.type, f"第{ent.first_appearance}章")
        if len(state.entities) > 10:
            table.add_row("...", "", "")
        console.print(table)

    if state.plot_threads:
        console.print(f"\n[bold]剧情线: {len(state.plot_threads)}[/]")
        for pt in state.plot_threads:
            status_icon = {"active": "🟢", "resolved": "✅", "dormant": "💤"}.get(pt.status, "❓")
            console.print(f"  {status_icon} {pt.name} ({pt.status})")

    console.print()


def run_status() -> None:
    """CLI entry point for status command."""
    root = project_fs.find_project_root()
    if root is None:
        error("未找到 AZNovel 项目。请先运行 'aznovel init'")
        raise typer.Exit(1)
    _show_status(root)
