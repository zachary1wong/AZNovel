"""AZNovel CLI application entry point."""

from __future__ import annotations

import asyncio

import typer

from aznovel.utils.rich_ui import console

app = typer.Typer(
    name="aznovel",
    help="AZNovel - AI辅助中文网文写作工具",
    invoke_without_command=True,
    no_args_is_help=False,
)


@app.callback()
def main_callback(
    ctx: typer.Context,
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称（跳过选择，直接使用指定配置）"),
):
    """不带参数时自动判断：项目目录内进入对话模式，否则进入初始化。"""
    if ctx.invoked_subcommand is not None:
        return

    from aznovel.storage.project_fs import find_project_root

    root = find_project_root()
    if root:
        # In a project directory → enter chat mode
        _auto_chat(profile_name=profile)
    else:
        # Not in a project → enter init mode
        _auto_init(profile_name=profile)


def _auto_chat(profile_name: str | None = None):
    """Enter chat mode (used when running aznovel without args in a project)."""
    from aznovel.cli.chat_cmd import chat_loop
    from aznovel.cli.config_cmd import build_llm_config
    from aznovel.llm.provider_factory import create_provider
    from aznovel.storage.project_fs import require_project_root

    root = require_project_root()
    llm_config = build_llm_config(profile_name)
    provider = create_provider(llm_config)
    write_mode = "default"

    async def _run():
        try:
            await chat_loop(provider, root, write_mode=write_mode)
        finally:
            await provider.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n再见！")


def _auto_init(profile_name: str | None = None):
    """Enter init mode (used when running aznovel without args outside a project)."""
    from aznovel.cli.config_cmd import (
        select_or_create_profile, apply_profile_to_config,
        load_profiles, _GLOBAL_CONFIG,
    )
    from aznovel.cli.init_cmd import run_init
    from aznovel.utils.rich_ui import ProgressTracker

    # Step 1: Get LLM profile (before starting progress tracker)
    if profile_name:
        # Use named profile directly (no interactive selection)
        profiles = load_profiles()
        found = [p for p in profiles if p.get("name") == profile_name]
        if not found:
            from aznovel.utils.rich_ui import error
            error(f"未找到 LLM 配置: {profile_name}")
            error(f"可用配置: {', '.join(p['name'] for p in profiles)}")
            raise typer.Exit(1)
        profile = found[0]
    else:
        profile = select_or_create_profile()

    if profile is None:
        console.print("未选择 LLM 配置，已取消。")
        raise typer.Exit(1)

    # Step 2: Apply to global config so init conversation can use it
    apply_profile_to_config(profile, _GLOBAL_CONFIG)

    # Step 3: Start progress tracker and run init
    phases = ["参数收集", "文件分析", "大纲生成", "大纲审核", "项目创建"]
    tracker = ProgressTracker(phases)

    run_init(".", None, None, llm_profile=profile, progress_tracker=tracker)


@app.command()
def chat(
    fast: bool = typer.Option(False, "--fast", "-f", help="快速模式：跳过审查，每章只需2次LLM调用"),
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称"),
):
    """进入AI对话模式，用自然语言指挥写作。"""
    from aznovel.cli.chat_cmd import chat_loop
    from aznovel.cli.config_cmd import build_llm_config
    from aznovel.llm.provider_factory import create_provider
    from aznovel.storage.project_fs import require_project_root

    root = require_project_root()
    llm_config = build_llm_config(profile)
    provider = create_provider(llm_config)
    write_mode = "minimal" if fast else "default"

    async def _run():
        try:
            await chat_loop(provider, root, write_mode=write_mode)
        finally:
            await provider.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n再见！")


@app.command()
def init(
    directory: str = typer.Argument(".", help="项目目录"),
    title: str = typer.Option(None, "--title", "-t", help="小说标题（不填则进入对话模式）"),
    genre: str = typer.Option(None, "--genre", "-g", help="题材类型"),
    prot_name: str = typer.Option(None, "--protagonist", "-p", help="主角姓名"),
    prot_cultivation: str = typer.Option(None, "--identity", help="初始身份/境界"),
    prot_goal: str = typer.Option(None, "--goal", help="初始目标"),
    golden_finger: str = typer.Option(None, "--golden-finger", help="金手指/特殊能力"),
):
    """初始化新项目。不带参数时进入AI对话模式，自动收集创作想法。"""
    from aznovel.cli.init_cmd import run_init
    run_init(directory, title, genre, prot_name, prot_cultivation, prot_goal, golden_finger)


@app.command()
def write(
    chapter: int = typer.Option(..., "--chapter", "-c", help="章节编号"),
    mode: str = typer.Option("default", "--mode", "-m", help="模式: default/fast/minimal"),
    outline: str = typer.Option(None, "--outline", "-o", help="大纲文件路径"),
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称"),
):
    """写作新章节（完整流水线）。"""
    from aznovel.cli.write_cmd import run_write
    run_write(chapter, mode, outline, profile_name=profile)


@app.command()
def review(
    chapter: int = typer.Option(..., "--chapter", "-c", help="章节编号"),
    dims: str = typer.Option(None, "--dims", "-d", help="审查维度（逗号分隔）"),
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称"),
):
    """审查已有章节。"""
    from aznovel.cli.review_cmd import run_review
    run_review(chapter, dims, profile_name=profile)


@app.command()
def rewrite(
    chapter: int = typer.Option(..., "--chapter", "-c", help="要重写的章节编号"),
    modification: str = typer.Option(..., "--modification", "-m", help="修改要求描述"),
    cascade: bool = typer.Option(False, "--cascade", help="强制删除后续章节（不询问）"),
    mode: str = typer.Option("default", "--mode", help="模式: default/fast/minimal"),
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称"),
):
    """重写已有章节。如果改动影响后续章节，会提示删除。"""
    from aznovel.cli.rewrite_cmd import run_rewrite
    run_rewrite(chapter, modification, cascade, mode, profile_name=profile)


@app.command()
def status():
    """显示项目状态。"""
    from aznovel.cli.status_cmd import run_status
    run_status()


@app.command("config")
def config_cmd(
    action: str = typer.Argument(..., help="操作: get/set/init"),
    key: str = typer.Argument(None, help="配置键名"),
    value: str = typer.Argument(None, help="配置值（set时需要）"),
    global_level: bool = typer.Option(False, "--global", "-g", help="保存到全局配置"),
):
    """管理配置。"""
    from aznovel.cli.config_cmd import run_config
    run_config(action, key, value, global_level)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
