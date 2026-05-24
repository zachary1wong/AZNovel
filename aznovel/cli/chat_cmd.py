"""Unified conversational interface - natural language driven."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from aznovel.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一个AI小说写作助手，正在帮用户管理一个网文写作项目。

## 当前项目状态
{project_status}

## 你可以执行的操作
{actions_desc}

## 回复规则
- 用简洁自然的中文回复
- 当用户要求执行操作时，先确认理解是否正确，然后输出执行指令
- 执行指令格式（单独一行）：
  ===ACTION==={{"action": "动作名", "params": {{...}}}}===
- 如果用户只是聊天或问问题，正常回复即可，不需要输出指令
- 对于模糊的请求，先追问确认

## 可用的动作
1. write_next — 写下一章（自动计算章节号）
2. write_chapter — 写指定章节，params: {{"chapter": 数字}}
3. write_batch — 连续写多章，params: {{"count": 数字}}
4. review_chapter — 审查章节，params: {{"chapter": 数字}}
5. review_latest — 审查最新一章
6. show_status — 显示项目状态
7. show_chapter — 查看章节内容，params: {{"chapter": 数字}}
8. update_setting — 更新设定，params: {{"file": "文件名", "content": "内容"}}
9. generate_outline — 重新生成小说大纲
10. revise_outline — 修改大纲，params: {{"feedback": "修改意见"}}
11. show_outline — 显示当前大纲
12. rewrite_chapter — 重写章节，params: {{"chapter": 数字, "modification": "修改要求", "cascade": false}}
"""

_ACTIONS_DESC = """- 写下一章：接着当前进度写下一章
- 连续写N章：一口气写多章（每章独立走完整流水线）
- 审查章节：检查某一章的质量
- 查看进度：显示项目状态和已完成章节
- 查看章节：读取某一章的内容
- 更新设定：修改世界观、人物卡等设定文件
- 生成大纲：重新生成小说大纲
- 修改大纲：根据反馈修改大纲
- 查看大纲：显示当前大纲
- 重写章节：修改已有章节，如果影响后续会提示删除"""


def _format_project_status(status_data: dict) -> str:
    """Format project status for the system prompt."""
    lines = []
    pi = status_data.get("project_info", {})
    lines.append(f"小说标题: {pi.get('title', '未设置')}")
    lines.append(f"题材: {pi.get('genre', '未设置')}")

    prog = status_data.get("progress", {})
    lines.append(f"已完成章节: {prog.get('current_chapter', 0)}")
    lines.append(f"目标章数: {pi.get('target_chapters', 600)}")

    prot = status_data.get("protagonist", {})
    if prot.get("name"):
        lines.append(f"主角: {prot['name']} ({prot.get('cultivation', '')})")
        lines.append(f"主角目标: {prot.get('current_goal', '')}")

    chapters = status_data.get("existing_chapters", [])
    if chapters:
        lines.append(f"已有章节: {', '.join(chapters[-10:])}")
        if len(chapters) > 10:
            lines.append(f"  ... 共 {len(chapters)} 章")

    return "\n".join(lines)


def _parse_action(reply: str) -> dict | None:
    """Extract action from LLM reply."""
    if "===ACTION===" not in reply:
        return None
    try:
        start = reply.index("===ACTION===") + len("===ACTION===")
        end = reply.index("===", start)
        json_str = reply[start:end].strip()
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None


async def _run_action(action: dict, provider: LLMProvider, root: Path, write_mode: str = "default", btw_monitor=None) -> bool:
    """Execute an action."""
    from aznovel.cli.config_cmd import load_config
    from aznovel.utils.rich_ui import console
    from aznovel.cli.write_cmd import _run_write_inner
    from aznovel.cli.review_cmd import _run_review_inner
    from aznovel.cli.status_cmd import _show_status
    from aznovel.storage import project_fs
    from aznovel.utils.text import extract_chapter_number

    name = action.get("action", "")
    params = action.get("params", {})
    paths = project_fs.project_paths(root)

    config_data = load_config()
    word_target = config_data.get("word_target", 2000)

    def _on_step(msg):
        if btw_monitor:
            btw_monitor.set_step(msg)

    if name == "show_status":
        _show_status(root)
        return True

    elif name == "show_chapter":
        chapter = params.get("chapter", 1)
        path = paths["chapters_dir"] / f"第{chapter:03d}章.md"
        if path.exists():
            from aznovel.utils.rich_ui import panel
            panel(f"第{chapter}章", path.read_text(encoding="utf-8"))
        else:
            from aznovel.utils.rich_ui import error
            error(f"第{chapter}章不存在")
        return True

    elif name == "write_next":
        # Find next chapter number
        chapters_dir = paths["chapters_dir"]
        existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []
        if existing:
            last = extract_chapter_number(existing[-1].name)
            next_ch = (last or 0) + 1
        else:
            next_ch = 1
        return await _run_write_inner(provider, root, next_ch, write_mode, word_target, on_step=_on_step)

    elif name == "write_chapter":
        chapter = params.get("chapter", 1)
        return await _run_write_inner(provider, root, chapter, write_mode, word_target, on_step=_on_step)

    elif name == "write_batch":
        count = params.get("count", 3)
        chapters_dir = paths["chapters_dir"]
        existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []
        if existing:
            last = extract_chapter_number(existing[-1].name)
            start = (last or 0) + 1
        else:
            start = 1

        from aznovel.utils.rich_ui import info
        success_count = 0
        for i in range(count):
            ch = start + i
            info(f"\n{'='*40}")
            info(f"写作第 {ch}/{start + count - 1} 章")
            info(f"{'='*40}")
            ok = await _run_write_inner(provider, root, ch, write_mode, word_target, on_step=_on_step)
            if ok:
                success_count += 1
            else:
                from aznovel.utils.rich_ui import error
                error(f"第{ch}章写作失败，停止批量写作。")
                break

        from aznovel.utils.rich_ui import success
        success(f"\n批量写作完成！成功 {success_count}/{count} 章。")
        return success_count > 0

    elif name == "review_chapter":
        chapter = params.get("chapter", 1)
        return await _run_review_inner(provider, root, chapter)

    elif name == "review_latest":
        chapters_dir = paths["chapters_dir"]
        existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []
        if not existing:
            from aznovel.utils.rich_ui import error
            error("还没有任何章节")
            return False
        last = extract_chapter_number(existing[-1].name) or 1
        return await _run_review_inner(provider, root, last)

    elif name == "update_setting":
        file = params.get("file", "")
        content = params.get("content", "")
        if file and content:
            path = paths["settings_dir"] / file
            path.write_text(content, encoding="utf-8")
            from aznovel.utils.rich_ui import success
            success(f"设定已更新: {file}")
            return True

    elif name == "show_outline":
        outline_json = root / "大纲" / "outline.json"
        outline_md = root / "大纲" / "总纲.md"
        if outline_json.exists():
            from aznovel.utils.rich_ui import panel
            content = outline_json.read_text(encoding="utf-8")
            panel("当前大纲 (JSON)", content)
            return True
        elif outline_md.exists():
            from aznovel.utils.rich_ui import panel
            content = outline_md.read_text(encoding="utf-8")
            panel("当前大纲", content)
            return True
        else:
            from aznovel.utils.rich_ui import warn
            warn("还没有大纲。可以用'生成大纲'来创建。")
            return False

    elif name == "generate_outline":
        from aznovel.core.analyzer import generate_outline
        from aznovel.storage.state_store import StateStore

        store = StateStore(root)
        state = store.load()

        title = state.project_info.title
        genre = state.project_info.genre
        protagonist = {
            "name": state.protagonist.name,
            "identity": state.protagonist.cultivation,
            "goal": state.protagonist.current_goal,
            "golden_finger": ", ".join(state.protagonist.special_abilities),
        }
        target = state.project_info.target_chapters
        per_vol = state.project_info.chapters_per_volume

        from aznovel.utils.rich_ui import info
        info(f"正在为《{title}》生成大纲（{target}章，{target // per_vol}卷）...")

        outline = await generate_outline(
            provider, title, genre, protagonist,
            target_chapters=target,
            chapters_per_volume=per_vol,
        )

        if "error" in outline:
            from aznovel.utils.rich_ui import error
            error(f"大纲生成失败: {outline['error']}")
            return False

        # Save outline
        from aznovel.cli.init_cmd import _save_outline
        _save_outline(root, title, outline)

        # Display
        from aznovel.cli.init_cmd import _display_outline
        _display_outline(outline)

        from aznovel.utils.rich_ui import success
        success("大纲已生成并保存！")
        return True

    elif name == "revise_outline":
        from aznovel.core.analyzer import revise_outline
        import json as json_mod

        feedback = params.get("feedback", "")
        if not feedback:
            from aznovel.utils.rich_ui import warn
            warn("请提供修改意见。")
            return False

        # Load current outline
        outline_json = root / "大纲" / "outline.json"
        if not outline_json.exists():
            from aznovel.utils.rich_ui import warn
            warn("还没有大纲。请先用'生成大纲'创建。")
            return False

        current = json_mod.loads(outline_json.read_text(encoding="utf-8"))

        from aznovel.utils.rich_ui import info
        info("正在根据反馈修改大纲...")

        revised = await revise_outline(provider, current, feedback)

        if "error" in revised:
            from aznovel.utils.rich_ui import error
            error(f"大纲修改失败: {revised['error']}")
            return False

        # Save revised outline
        from aznovel.cli.init_cmd import _save_outline
        from aznovel.storage.state_store import StateStore
        store = StateStore(root)
        state = store.load()
        _save_outline(root, state.project_info.title, revised)

        # Display
        from aznovel.cli.init_cmd import _display_outline
        _display_outline(revised)

        from aznovel.utils.rich_ui import success
        success("大纲已更新！")
        return True

    elif name == "rewrite_chapter":
        from aznovel.core.pipeline import WritingPipeline

        chapter = params.get("chapter", 0)
        modification = params.get("modification", "")
        cascade = params.get("cascade", False)

        if not chapter:
            from aznovel.utils.rich_ui import warn
            warn("请指定要重写的章节号。")
            return False
        if not modification:
            from aznovel.utils.rich_ui import warn
            warn("请提供修改要求。")
            return False

        pipeline = WritingPipeline(provider, root, word_target=word_target)

        # Check if chapter exists
        ch_path = paths["chapters_dir"] / f"第{chapter:03d}章.md"
        if not ch_path.exists():
            from aznovel.utils.rich_ui import error
            error(f"第{chapter}章不存在。请用 write 命令新建。")
            return False

        # If not forced cascade, let the pipeline analyze and warn
        if not cascade:
            # The pipeline's rewrite_chapter handles analysis and warning
            # But we need user confirmation for cascade
            subsequent = pipeline._get_subsequent_chapters(chapter)
            if subsequent:
                from aznovel.utils.rich_ui import info, warn
                info(f"第{chapter}章之后还有 {len(subsequent)} 章：{', '.join(f'第{c}章' for c in subsequent)}")

                # Let pipeline analyze
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
            chapter, modification, mode=write_mode, force_cascade=cascade, on_step=_on_step
        )

        if ok and was_cascaded:
            from aznovel.utils.rich_ui import info
            info("后续章节已删除，记得重新生成。")

        return ok

    return False


async def chat_loop(provider: LLMProvider, root: Path, write_mode: str = "default") -> None:
    """Main conversational loop."""
    from aznovel.storage.state_store import StateStore
    from aznovel.storage import project_fs
    from aznovel.utils.rich_ui import console

    store = StateStore(root)
    paths = project_fs.project_paths(root)

    # Build initial project status
    state = store.load()
    chapters_dir = paths["chapters_dir"]
    existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []
    status_data = state.model_dump()
    status_data["existing_chapters"] = [f.name for f in existing]

    system = _SYSTEM_PROMPT.format(
        project_status=_format_project_status(status_data),
        actions_desc=_ACTIONS_DESC,
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    # Welcome message
    console.print(f"\n[bold cyan]🤖 AZNovel 写作助手[/]")
    console.print(f"项目: [bold]{state.project_info.title}[/] | 已完成 {len(existing)} 章")
    console.print("输入你的想法，我来帮你执行。输入 [bold]退出[/] 结束。\n")

    while True:
        try:
            user_input = console.input("[bold green]你 > [/]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n再见！")
            break

        if not user_input.strip():
            continue

        if user_input.strip() in ("退出", "quit", "exit", "q", "再见"):
            console.print("再见！")
            break

        messages.append({"role": "user", "content": user_input})

        # Get LLM response
        resp = await provider.chat(messages, temperature=0.5, max_tokens=2048)
        reply = resp.content
        messages.append({"role": "assistant", "content": reply})

        # Parse action
        action = _parse_action(reply)

        # Print the text part (before ===ACTION===)
        text_part = reply.split("===ACTION===")[0].strip() if "===ACTION===" in reply else reply
        if text_part:
            console.print(f"\n[bold cyan]🤖 AZNovel[/]\n")
            console.print(text_part)

        if action:
            # Refresh status before action
            state = store.load()
            existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []
            status_data = state.model_dump()
            status_data["existing_chapters"] = [f.name for f in existing]

            # Start /btw monitor
            from aznovel.utils.rich_ui import BtwMonitor
            btw = BtwMonitor(root)
            btw.start()

            console.print()
            console.print("[dim]提示：操作执行期间可输入 /btw status 查看状态[/]\n")

            try:
                # Run action and btw monitor concurrently
                action_coro = _run_action(action, provider, root, write_mode, btw_monitor=btw)
                monitor_coro = btw.monitor_loop()

                action_task = asyncio.create_task(action_coro)
                monitor_task = asyncio.create_task(monitor_coro)

                ok = await action_task
                btw.stop()
                await monitor_task
            except Exception as e:
                btw.stop()
                from aznovel.utils.rich_ui import error
                error(f"操作执行出错: {e}")
                ok = False
            console.print()

            if ok:
                # Update system prompt with new status
                state = store.load()
                existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []
                status_data = state.model_dump()
                status_data["existing_chapters"] = [f.name for f in existing]
                system = _SYSTEM_PROMPT.format(
                    project_status=_format_project_status(status_data),
                    actions_desc=_ACTIONS_DESC,
                )
                messages[0] = {"role": "system", "content": system}

                messages.append({
                    "role": "user",
                    "content": f"[操作已完成，项目状态已更新。当前已完成 {len(existing)} 章。]"
                })
                resp2 = await provider.chat(messages, temperature=0.3, max_tokens=512)
                messages.append({"role": "assistant", "content": resp2.content})

        console.print()
