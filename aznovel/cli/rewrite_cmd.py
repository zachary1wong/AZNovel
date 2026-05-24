"""Rewrite chapter CLI command."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from aznovel.core.pipeline import WritingPipeline
from aznovel.llm.provider_factory import create_provider
from aznovel.storage.project_fs import require_project_root
from aznovel.utils.rich_ui import console, error, info, warn


async def _run_rewrite_inner(
    provider, root: Path, chapter: int, modification: str,
    cascade: bool, mode: str, word_target: int = 2000,
) -> bool:
    """Core rewrite logic, callable from chat or CLI."""
    pipeline = WritingPipeline(provider, root, word_target=word_target)

    # Check chapter exists
    from aznovel.utils.text import chapter_filename
    from aznovel.storage import project_fs
    paths = project_fs.project_paths(root)
    ch_path = paths["chapters_dir"] / chapter_filename(chapter)

    if not ch_path.exists():
        error(f"第{chapter}章不存在。请用 write 命令新建。")
        return False

    # If not forced cascade, analyze and ask for confirmation
    if not cascade:
        subsequent = pipeline._get_subsequent_chapters(chapter)
        if subsequent:
            info(f"第{chapter}章之后还有 {len(subsequent)} 章：{', '.join(f'第{c}章' for c in subsequent)}")

            analysis = await pipeline.analyze_change(chapter, modification)
            is_structural = analysis.get("structural", True)
            reason = analysis.get("reason", "")

            if is_structural:
                warn(f"此修改属于结构性改动：{reason}")
                warn("后续章节将被删除，需要重新生成。")
                confirm = console.input("[bold green]确认删除后续章节并重写？(y/n) > [/]")
                if confirm.strip().lower() not in ("y", "yes", "是", "好", "确认", ""):
                    info("已取消重写。")
                    return False
                cascade = True
            else:
                info(f"此修改属于非结构性改动：{reason}")
                info("后续章节保持不变。")

    ok, was_cascaded = await pipeline.rewrite_chapter(
        chapter, modification, mode=mode, force_cascade=cascade,
    )

    if ok and was_cascaded:
        info("后续章节已删除，记得重新生成。")

    return ok


def run_rewrite(chapter: int, modification: str, cascade: bool, mode: str, profile_name: str | None = None) -> None:
    """CLI entry point for rewrite command."""
    root = require_project_root()

    from aznovel.cli.config_cmd import build_llm_config, load_config
    llm_config = build_llm_config(profile_name)

    config_data = load_config(profile_name)
    word_target = config_data.get("word_target", 2000)
    provider = create_provider(llm_config)

    console.print(f"\n[bold]重写第{chapter:03d}章[/]")
    console.print(f"[dim]修改要求: {modification}[/]\n")

    async def _run():
        try:
            return await _run_rewrite_inner(
                provider, root, chapter, modification, cascade, mode, word_target,
            )
        finally:
            await provider.close()

    try:
        result = asyncio.run(_run())
        if result:
            console.print(f"\n[bold green]重写完成！[/]")
        else:
            console.print(f"\n[bold red]重写失败。[/]")
            raise typer.Exit(1)
    except Exception as e:
        error(f"重写过程出错: {e}")
        raise typer.Exit(1)
