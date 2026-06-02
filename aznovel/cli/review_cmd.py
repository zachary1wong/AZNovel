"""Review chapter CLI command."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from aznovel.core.contract_manager import ContractManager
from aznovel.core.review_engine import ReviewEngine, format_review_report
from aznovel.llm.base import LLMProvider
from aznovel.llm.provider_factory import create_provider
from aznovel.models.contract import ReviewContract
from aznovel.storage import project_fs
from aznovel.storage.project_fs import require_project_root
from aznovel.utils.rich_ui import console, error, success, warn


def _safe_print_report(report: str, report_path: Path) -> None:
    """Print a review report without failing the review action on terminal I/O."""
    try:
        console.print(report)
    except (BlockingIOError, OSError) as exc:
        try:
            warn(f"审查报告已保存，但终端输出失败: {exc}")
            console.print(f"[dim]报告路径: {report_path}[/]")
        except (BlockingIOError, OSError):
            pass


async def _run_review_inner(provider: LLMProvider, root: Path, chapter: int) -> bool:
    """Core review logic, callable from chat or CLI."""
    paths = project_fs.project_paths(root)

    chapter_file = paths["chapters_dir"] / f"第{chapter:03d}章.md"
    if not chapter_file.exists():
        error(f"未找到章节文件: {chapter_file}")
        return False

    content = chapter_file.read_text(encoding="utf-8")
    lines = content.split("\n")
    if lines and lines[0].startswith("# "):
        content = "\n".join(lines[1:]).strip()

    engine = ReviewEngine(provider)
    contract_mgr = ContractManager(root)

    contract = contract_mgr.load_review_contract(chapter)
    if contract is None:
        contract = ReviewContract(chapter_number=chapter)

    console.print(f"\n[bold]审查第{chapter:03d}章...[/]\n")

    result = await engine.review_chapter(content, contract)
    report = format_review_report(result)

    report_path = paths["reviews_dir"] / f"chapter_{chapter:03d}_review.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    _safe_print_report(report, report_path)

    if result.passed:
        success("审查通过！")
    else:
        error(f"审查未通过（{result.blocking_count} 个阻断问题）")
    return result.passed


def run_review(chapter: int, dimensions: str | None, profile_name: str | None = None) -> None:
    """CLI entry point for review command."""
    root = require_project_root()

    from aznovel.cli.config_cmd import build_llm_config
    llm_config = build_llm_config(profile_name)

    provider = create_provider(llm_config)

    console.print(f"\n[bold]审查第{chapter:03d}章...[/]\n")

    async def _run():
        try:
            return await _run_review_inner(provider, root, chapter)
        finally:
            await provider.close()

    try:
        asyncio.run(_run())
    except Exception as e:
        error(f"审查过程出错: {e}")
        raise typer.Exit(1)
