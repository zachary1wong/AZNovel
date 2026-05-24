"""Write chapter CLI command."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from aznovel.core.pipeline import WritingPipeline
from aznovel.llm.base import LLMProvider
from aznovel.llm.provider_factory import create_provider
from aznovel.storage.project_fs import require_project_root
from aznovel.utils.rich_ui import console, error


async def _run_write_inner(
    provider: LLMProvider, root: Path, chapter: int, mode: str, word_target: int = 2000, on_step=None
) -> bool:
    """Core write logic, callable from chat or CLI."""
    pipeline = WritingPipeline(provider, root, word_target=word_target)
    return await pipeline.write_chapter(chapter, mode=mode, on_step=on_step)


def run_write(chapter: int, mode: str, outline_file: str | None, profile_name: str | None = None) -> None:
    """CLI entry point for write command."""
    root = require_project_root()

    from aznovel.cli.config_cmd import build_llm_config, load_config
    llm_config = build_llm_config(profile_name)

    config_data = load_config(profile_name)
    word_target = config_data.get("word_target", 2000)

    outline = None
    if outline_file:
        outline = json.loads(Path(outline_file).read_text(encoding="utf-8"))

    word_target = config_data.get("word_target", 2000)
    provider = create_provider(llm_config)

    console.print(f"\n[bold]开始写作第{chapter:03d}章 ({mode} 模式, 目标{word_target}字)[/]\n")

    async def _run():
        try:
            return await _run_write_inner(provider, root, chapter, mode, word_target)
        finally:
            await provider.close()

    try:
        result = asyncio.run(_run())
        if result:
            console.print(f"\n[bold green]写作完成！[/]")
        else:
            console.print(f"\n[bold red]写作失败。[/]")
            raise typer.Exit(1)
    except Exception as e:
        error(f"写作过程出错: {e}")
        raise typer.Exit(1)
