"""AZNovel CLI application entry point."""

from __future__ import annotations

import asyncio

import typer

from aznovel.utils.rich_ui import console

app = typer.Typer(
    name="aznovel",
    help="AZNovel - AI辅助中文小说写作CLI工具",
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
    overwrite: bool = typer.Option(False, "--overwrite", help="覆盖已有章节"),
):
    """写作新章节（完整流水线）。"""
    from aznovel.cli.write_cmd import run_write
    run_write(chapter, mode, outline, profile_name=profile, overwrite=overwrite)


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


@app.command("reverse-outline")
def reverse_outline_cmd(profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称")):
    """从已写章节反推大纲，方便检阅整本书结构。"""
    from aznovel.cli.chat_cmd import _run_action
    from aznovel.cli.config_cmd import build_llm_config
    from aznovel.llm.provider_factory import create_provider
    from aznovel.storage.project_fs import require_project_root

    root = require_project_root()
    llm_config = build_llm_config(profile)
    provider = create_provider(llm_config)

    async def _run():
        try:
            ok = await _run_action({"action": "reverse_outline", "params": {}}, provider, root)
            return ok
        finally:
            await provider.close()

    try:
        result = asyncio.run(_run())
        if not result:
            raise typer.Exit(1)
    except Exception as e:
        from aznovel.utils.rich_ui import error
        error(f"反推大纲失败: {e}")
        raise typer.Exit(1)


@app.command()
def polish(
    chapter: int = typer.Option(None, "--chapter", "-c", help="精修指定章节"),
    start: int = typer.Option(None, "--start", "-s", help="起始章节号"),
    end: int = typer.Option(None, "--end", "-e", help="结束章节号"),
    all_chapters: bool = typer.Option(False, "--all", "-a", help="精修全部章节"),
    careful: bool = typer.Option(False, "--careful", help="逐段精修模式，更仔细但更慢"),
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称"),
):
    """精修章节文字，修复语病和不通顺，不改剧情结构。"""
    from aznovel.cli.polish_cmd import run_polish
    run_polish(chapter=chapter, start=start, end=end, all_chapters=all_chapters, careful=careful, profile_name=profile)


@app.command("safe-repair")
def safe_repair_cmd(
    chapters: str = typer.Option(None, "--chapters", "-c", help="章节列表，例如 6,8,10；不填则全书"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只生成候选和报告，不覆盖正文"),
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称"),
):
    """执行最终安全修复：跨章节终检硬逻辑，只应用小补丁。"""
    from aznovel.cli.chat_cmd import _run_action
    from aznovel.cli.config_cmd import build_llm_config
    from aznovel.llm.provider_factory import create_provider
    from aznovel.storage.project_fs import require_project_root

    root = require_project_root()
    llm_config = build_llm_config(profile)
    provider = create_provider(llm_config)

    parsed_chapters = None
    if chapters:
        parsed_chapters = []
        for part in chapters.replace("，", ",").split(","):
            part = part.strip()
            if part:
                parsed_chapters.append(int(part))

    params = {"dry_run": dry_run}
    if parsed_chapters:
        params["chapters"] = parsed_chapters
    else:
        params["all"] = True

    async def _run():
        try:
            return await _run_action(
                {"action": "final_safe_repair", "params": params},
                provider,
                root,
            )
        finally:
            await provider.close()

    try:
        result = asyncio.run(_run())
        if not result:
            raise typer.Exit(1)
    except Exception as e:
        from aznovel.utils.rich_ui import error
        error(f"最终安全修复失败: {e}")
        raise typer.Exit(1)


@app.command("final-polish")
def final_polish_cmd(
    chapters: str = typer.Option(None, "--chapters", "-c", help="章节列表，例如 7,8,10；不填则全书"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只生成候选和报告，不覆盖正文"),
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称"),
):
    """执行终稿精修：只修出戏表达、薄弱过桥和小型文字瑕疵。"""
    from aznovel.cli.chat_cmd import _run_action
    from aznovel.cli.config_cmd import build_llm_config
    from aznovel.llm.provider_factory import create_provider
    from aznovel.storage.project_fs import require_project_root

    root = require_project_root()
    llm_config = build_llm_config(profile)
    provider = create_provider(llm_config)

    parsed_chapters = None
    if chapters:
        parsed_chapters = []
        for part in chapters.replace("，", ",").split(","):
            part = part.strip()
            if part:
                parsed_chapters.append(int(part))

    params = {"dry_run": dry_run}
    if parsed_chapters:
        params["chapters"] = parsed_chapters
    else:
        params["all"] = True

    async def _run():
        try:
            return await _run_action(
                {"action": "final_polish", "params": params},
                provider,
                root,
            )
        finally:
            await provider.close()

    try:
        result = asyncio.run(_run())
        if not result:
            raise typer.Exit(1)
    except Exception as e:
        from aznovel.utils.rich_ui import error
        error(f"终稿精修失败: {e}")
        raise typer.Exit(1)


@app.command("finalize")
def finalize_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="只生成候选和报告，不覆盖正文"),
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称"),
):
    """执行完稿流程：最终安全修复后，再做终稿精修。"""
    from aznovel.cli.chat_cmd import _run_action
    from aznovel.cli.config_cmd import build_llm_config
    from aznovel.llm.provider_factory import create_provider
    from aznovel.storage.project_fs import require_project_root

    root = require_project_root()
    llm_config = build_llm_config(profile)
    provider = create_provider(llm_config)

    async def _run():
        try:
            return await _run_action(
                {"action": "finalize_book", "params": {"all": True, "dry_run": dry_run}},
                provider,
                root,
            )
        finally:
            await provider.close()

    try:
        result = asyncio.run(_run())
        if not result:
            raise typer.Exit(1)
    except Exception as e:
        from aznovel.utils.rich_ui import error
        error(f"完稿流程失败: {e}")
        raise typer.Exit(1)


@app.command("rename-character")
def rename_character_cmd(
    old_name: str = typer.Option(..., "--from", "-f", help="旧角色名"),
    new_name: str = typer.Option(..., "--to", "-t", help="新角色名"),
    aliases: str = typer.Option(None, "--aliases", "-a", help="称谓映射，例如：小禾=小森,禾禾=森森"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只生成候选和报告，不覆盖项目文件"),
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称"),
):
    """受控角色改名：同步正文、大纲、设定、状态、契约和审查报告中的小名/昵称。"""
    from aznovel.cli.chat_cmd import _run_action
    from aznovel.cli.config_cmd import build_llm_config
    from aznovel.llm.provider_factory import create_provider
    from aznovel.storage.project_fs import require_project_root

    root = require_project_root()
    llm_config = build_llm_config(profile)
    provider = create_provider(llm_config)

    async def _run():
        try:
            return await _run_action(
                {
                    "action": "rename_character",
                    "params": {
                        "old_name": old_name,
                        "new_name": new_name,
                        "aliases": aliases,
                        "dry_run": dry_run,
                    },
                },
                provider,
                root,
            )
        finally:
            await provider.close()

    try:
        result = asyncio.run(_run())
        if not result:
            raise typer.Exit(1)
    except Exception as e:
        from aznovel.utils.rich_ui import error
        error(f"角色改名失败: {e}")
        raise typer.Exit(1)


@app.command("auto-run")
def auto_run_cmd(
    target: int = typer.Option(None, "--target", "-t", help="目标章数；不填则使用项目 target_chapters"),
    max_repair_attempts: int = typer.Option(2, "--max-repair-attempts", help="每章候选稿自动修复次数"),
    profile: str = typer.Option(None, "--profile", "-p", help="LLM配置名称"),
):
    """无人值守全流程：补写到目标章数，自动修复候选稿，最后终检和终稿精修。"""
    from aznovel.cli.chat_cmd import _run_action
    from aznovel.cli.config_cmd import build_llm_config
    from aznovel.llm.provider_factory import create_provider
    from aznovel.storage.project_fs import require_project_root

    root = require_project_root()
    llm_config = build_llm_config(profile)
    provider = create_provider(llm_config)

    params = {"max_repair_attempts": max_repair_attempts}
    if target:
        params["target"] = target

    async def _run():
        try:
            return await _run_action(
                {"action": "auto_run_book", "params": params},
                provider,
                root,
            )
        finally:
            await provider.close()

    try:
        result = asyncio.run(_run())
        if not result:
            raise typer.Exit(1)
    except Exception as e:
        from aznovel.utils.rich_ui import error
        error(f"无人值守全流程失败: {e}")
        raise typer.Exit(1)


@app.command("export")
def export_cmd(
    formats: str = typer.Option("epub", "--format", "-f", help="导出格式：epub/pdf/mobi/docx/all，可用逗号分隔多个格式"),
    output: str = typer.Option(None, "--output", "-o", help="输出文件或目录；多格式导出时必须是目录"),
):
    """导出全书为单个文件。"""
    from aznovel.cli.export_cmd import run_export
    run_export(formats=formats, output=output)


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
