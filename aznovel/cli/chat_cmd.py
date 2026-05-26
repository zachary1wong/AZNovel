"""Unified conversational interface - natural language driven."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from rich.markdown import Markdown

from aznovel.llm.base import LLMProvider

logger = logging.getLogger(__name__)

# Enable readline for arrow key support on Mac/Linux
try:
    import readline  # noqa: F401
except ImportError:
    pass


def _timed_input(prompt_text: str) -> str:
    """Input with arrow key support and styled prompt."""
    # Use ANSI escape codes for colored prompt, which readline can handle
    # \001 and \002 mark non-printable chars so readline calculates width correctly
    ansi_prompt = f"\001\033[1;32m\002{prompt_text}\001\033[0m\002"
    return input(ansi_prompt)

# Maximum messages to keep in history (excluding system prompt).
# Each action adds ~3 messages (user request, assistant reply, status update, summary),
# so 40 messages ≈ 10 actions of context.
_MAX_HISTORY = 40

_SYSTEM_PROMPT = """你是一个AI小说写作助手，正在帮用户管理一个网文写作项目。

## 当前项目状态
{project_status}

## 你可以执行的操作
{actions_desc}

## 回复规则
- 用简洁自然的中文回复
- 当用户要求执行操作时，先确认理解是否正确，然后输出执行指令
- 执行指令格式（单独一行）：
  ===ACTION==={{"action": "动作名", "params": {{...}}}}===ACTION_END===
- 如果用户只是聊天或问问题，正常回复即可，不需要输出指令
- 对于模糊的请求，先追问确认

## 处理用户提供的文件和需求
- 当用户提到文件路径时，系统会自动读取文件内容并附加在消息末尾（以 `--- 文件内容: xxx ---` 标记）
- 如果消息中包含文件内容，你应该仔细阅读并据此执行操作
- 用户的创作需求、角色设定、剧情要求等，应作为 requirements 传入 generate_outline 或作为 feedback 传入 revise_outline
- 执行 generate_outline 时，如果用户提供了需求文件，params 中必须包含 requirements 字段（填入文件内容摘要或关键需求点）

## 可用的动作
1. write_next — 写下一章（自动计算章节号）
2. write_chapter — 写指定章节，params: {{"chapter": 数字}}
3. write_batch — 连续写多章，params: {{"count": 数字}}
4. review_chapter — 审查章节，params: {{"chapter": 数字}}
5. review_latest — 审查最新一章
6. show_status — 显示项目状态
7. show_chapter — 查看章节内容，params: {{"chapter": 数字}}
8. update_setting — 更新设定，params: {{"file": "文件名", "content": "内容"}}
9. generate_outline — 重新生成小说大纲，params: {{"requirements": "用户的创作需求（可选，包含角色设定、剧情走向、风格要求等）"}}
10. revise_outline — 修改大纲，params: {{"feedback": "修改意见或需求内容"}}
11. show_outline — 显示当前大纲
12. rewrite_chapter — 重写章节，params: {{"chapter": 数字, "modification": "修改要求", "cascade": false}}
13. reverse_outline — 从已写章节反推大纲（不覆盖原大纲）
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
- 重写章节：修改已有章节，如果影响后续会提示删除
- 反推大纲：从已写章节反推出完整大纲，方便检阅"""


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
    """Extract action from LLM reply.

    Format: ===ACTION==={...}===ACTION_END===
    """
    if "===ACTION===" not in reply:
        return None
    try:
        start = reply.index("===ACTION===") + len("===ACTION===")
        end = reply.index("===ACTION_END===", start)
        json_str = reply[start:end].strip()
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None


def _truncate_messages(messages: list[dict[str, str]], max_history: int = _MAX_HISTORY) -> list[dict[str, str]]:
    """Keep system prompt + last max_history messages."""
    if len(messages) <= max_history + 1:
        return messages
    # Always keep messages[0] (system prompt)
    return [messages[0]] + messages[-(max_history):]


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
            error(f"第{chapter:03d}章不存在")
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
            info(f"写作第 {ch:03d}/{start + count - 1:03d} 章")
            info(f"{'='*40}")
            ok = await _run_write_inner(provider, root, ch, write_mode, word_target, on_step=_on_step)
            if ok:
                success_count += 1
            else:
                from aznovel.utils.rich_ui import error
                error(f"第{ch:03d}章写作失败，停止批量写作。")
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
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            from aznovel.utils.rich_ui import success
            success(f"设定已更新: {file}")
            return True
        else:
            from aznovel.utils.rich_ui import warn
            warn("更新设定需要 file 和 content 参数。")
            return False

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

        # Extract requirements from params
        requirements = params.get("requirements", "")
        # If requirements looks like a file path, try to read it
        if requirements and len(requirements) < 500 and Path(requirements).expanduser().exists():
            file_path = Path(requirements).expanduser()
            requirements = file_path.read_text(encoding="utf-8")

        # Check for existing chapter 1
        chapter_1_content = ""
        ch1_path = paths["chapters_dir"] / "第001章.md"
        if ch1_path.exists():
            chapter_1_content = ch1_path.read_text(encoding="utf-8")

        from aznovel.utils.rich_ui import info
        if requirements:
            info(f"正在为《{title}》生成大纲（{target}章，{target // per_vol}卷），已加载创作需求...")
        else:
            info(f"正在为《{title}》生成大纲（{target}章，{target // per_vol}卷）...")

        outline = await generate_outline(
            provider, title, genre, protagonist,
            target_chapters=target,
            chapters_per_volume=per_vol,
            requirements=requirements,
            chapter_1_content=chapter_1_content,
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

        # If feedback looks like a file path, read the file content
        if len(feedback) < 500 and Path(feedback).expanduser().exists():
            feedback = Path(feedback).expanduser().read_text(encoding="utf-8")

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
            error(f"第{chapter:03d}章不存在。请用 write 命令新建。")
            return False

        # If not forced cascade, let the pipeline analyze and warn
        if not cascade:
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
                    # Pause btw monitor to avoid stdin race
                    if btw_monitor:
                        btw_monitor.pause()
                    try:
                        confirm = console.input("[bold green]确认删除后续章节并重写？(y/n) > [/]")
                    finally:
                        if btw_monitor:
                            btw_monitor.resume()
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

    elif name == "reverse_outline":
        from aznovel.core.analyzer import reverse_outline
        from aznovel.storage.state_store import StateStore

        chapters_dir = paths["chapters_dir"]
        chapter_files = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []
        if not chapter_files:
            from aznovel.utils.rich_ui import warn
            warn("还没有任何章节，无法反推大纲。")
            return False

        # Read all chapters
        from aznovel.utils.text import extract_chapter_number
        chapters_data = []
        for f in chapter_files:
            num = extract_chapter_number(f.name)
            if num:
                content = f.read_text(encoding="utf-8")
                # Extract title from first line
                first_line = content.split("\n")[0].strip().lstrip("#").strip()
                title_text = first_line if first_line else f"第{num}章"
                chapters_data.append({
                    "number": num,
                    "title": title_text,
                    "content": content,
                })

        if not chapters_data:
            from aznovel.utils.rich_ui import warn
            warn("无法识别章节文件。")
            return False

        store = StateStore(root)
        state = store.load()

        from aznovel.utils.rich_ui import info
        info(f"正在从 {len(chapters_data)} 章内容反推大纲...")

        outline = await reverse_outline(
            provider, chapters_data,
            title=state.project_info.title,
            genre=state.project_info.genre,
        )

        if "error" in outline:
            from aznovel.utils.rich_ui import error
            error(f"反推大纲失败: {outline['error']}")
            return False

        # Save to different paths (not overwriting original outline)
        outline_dir = root / "大纲"
        outline_dir.mkdir(parents=True, exist_ok=True)

        outline_json_path = outline_dir / "反推大纲.json"
        outline_json_path.write_text(
            json.dumps(outline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Generate readable markdown
        md_lines = [f"# {state.project_info.title} — 反推大纲\n"]
        master = outline.get("master_outline", "")
        if master:
            md_lines.append(f"## 总纲\n{master}\n")
        for vol in outline.get("volumes", []):
            vol_num = vol.get("volume", "?")
            vol_title = vol.get("title", "")
            md_lines.append(f"## 第{vol_num}卷 {vol_title}\n")
            md_lines.append(f"**概述**：{vol.get('summary', '')}\n")
            conflicts = vol.get("key_conflicts", [])
            if conflicts:
                md_lines.append(f"**核心冲突**：{', '.join(conflicts)}\n")
            climax = vol.get("climax", "")
            if climax:
                md_lines.append(f"**高潮**：{climax}\n")
            chapters_list = vol.get("chapters", [])
            if chapters_list:
                md_lines.append("### 章节明细\n")
                md_lines.append("| 章节 | 标题 | 目标 | 剧情摘要 |")
                md_lines.append("|------|------|------|----------|")
                for ch in chapters_list:
                    md_lines.append(
                        f"| 第{ch.get('chapter', '?')}章 | {ch.get('title', '')} | {ch.get('goal', '')} | {ch.get('summary', '')} |"
                    )
                md_lines.append("")

        outline_md_path = outline_dir / "反推总纲.md"
        outline_md_path.write_text("\n".join(md_lines), encoding="utf-8")

        # Display
        from aznovel.cli.init_cmd import _display_outline
        _display_outline(outline)

        from aznovel.utils.rich_ui import success
        success(f"反推大纲已保存！")
        info(f"  JSON: {outline_json_path.relative_to(root)}")
        info(f"  Markdown: {outline_md_path.relative_to(root)}")
        return True

    return False


def _inject_file_contents(user_input: str, root: Path) -> str:
    """Detect file paths in user input and inject their contents."""
    import re

    # Match quoted file paths or paths that look like file references
    patterns = [
        r"'(/[^']+)'",           # '/path/to/file'
        r'"(/[^"]+)"',           # "/path/to/file"
        r'(/[a-zA-Z0-9_./\-]+\.[a-zA-Z]{1,4})',  # /path/to/file.ext
    ]

    files_found = []
    for pattern in patterns:
        for match in re.finditer(pattern, user_input):
            path_str = match.group(1) if match.lastindex else match.group(0)
            p = Path(path_str).expanduser()
            if p.exists() and p.is_file():
                files_found.append(p)

    if not files_found:
        return user_input

    # Deduplicate
    seen = set()
    unique_files = []
    for f in files_found:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)

    # Read and inject file contents
    parts = [user_input]
    for f in unique_files:
        try:
            content = f.read_text(encoding="utf-8")
            if len(content) > 50000:
                content = content[:50000] + "\n\n[... 文件过长，已截断 ...]"
            parts.append(f"\n\n--- 文件内容: {f.name} ---\n{content}\n--- 文件内容结束 ---")
        except Exception:
            pass

    return "".join(parts)


def _get_status_data(store, paths) -> dict:
    """Build status data dict for system prompt."""
    state = store.load()
    chapters_dir = paths["chapters_dir"]
    existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []
    status_data = state.model_dump()
    status_data["existing_chapters"] = [f.name for f in existing]
    return status_data


async def _heartbeat(btw) -> None:
    """Periodically print elapsed time during long-running actions."""
    import time
    start = time.time()
    try:
        while True:
            await asyncio.sleep(10)
            elapsed = int(time.time() - start)
            step = btw.get_step()
            if step:
                sys.stdout.write(f"\r\033[K\033[2m▸ {step} ({elapsed}s)\033[0m\n")
            else:
                sys.stdout.write(f"\r\033[K\033[2m▸ 执行中... ({elapsed}s)\033[0m\n")
            sys.stdout.flush()
    except asyncio.CancelledError:
        pass


async def chat_loop(provider: LLMProvider, root: Path, write_mode: str = "default") -> None:
    """Main conversational loop."""
    from aznovel.storage.state_store import StateStore
    from aznovel.storage import project_fs
    from aznovel.utils.rich_ui import console

    store = StateStore(root)
    paths = project_fs.project_paths(root)

    # Build initial project status
    status_data = _get_status_data(store, paths)

    system = _SYSTEM_PROMPT.format(
        project_status=_format_project_status(status_data),
        actions_desc=_ACTIONS_DESC,
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    # Welcome message
    state = store.load()
    chapters_dir = paths["chapters_dir"]
    existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []
    console.print(f"\n[bold cyan]AZNovel 写作助手[/]")
    console.print(f"项目: [bold]{state.project_info.title}[/] | 已完成 {len(existing)} 章")
    console.print("输入你的想法，我来帮你执行。输入 [bold]退出[/] 结束。\n")

    try:
        while True:
            try:
                user_input = _timed_input("你 > ")
                print()  # newline after input
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break

            if not user_input.strip():
                continue

            if user_input.strip() in ("退出", "quit", "exit", "q", "再见"):
                console.print("再见！")
                break

            # Detect file paths and read content
            user_input = _inject_file_contents(user_input, root)

            messages.append({"role": "user", "content": user_input})

            # Get LLM response with spinner
            try:
                with console.status("[dim]思考中...[/]", spinner="dots"):
                    resp = await provider.chat(messages, temperature=0.5, max_tokens=2048)
            except Exception as e:
                from aznovel.utils.rich_ui import error
                error(f"LLM 调用失败: {e}")
                # Remove the failed user message
                messages.pop()
                continue

            reply = resp.content
            messages.append({"role": "assistant", "content": reply})

            # Parse action
            action = _parse_action(reply)

            # Print the text part (before ===ACTION===)
            text_part = reply.split("===ACTION===")[0].strip() if "===ACTION===" in reply else reply
            if text_part:
                console.print(f"\n[bold cyan]AZNovel[/]\n")
                console.print(Markdown(text_part))

            if action:
                # Refresh status
                status_data = _get_status_data(store, paths)

                # Start /btw monitor
                from aznovel.utils.rich_ui import BtwMonitor
                btw = BtwMonitor(root)
                btw.start()

                console.print()
                console.print("[dim]提示：操作执行期间可输入 /btw status 查看状态[/]\n")

                monitor_task = None
                heartbeat_task = None
                try:
                    # Run action, btw monitor, and heartbeat concurrently
                    action_coro = _run_action(action, provider, root, write_mode, btw_monitor=btw)
                    monitor_coro = btw.monitor_loop()
                    heartbeat_coro = _heartbeat(btw)

                    action_task = asyncio.create_task(action_coro)
                    monitor_task = asyncio.create_task(monitor_coro)
                    heartbeat_task = asyncio.create_task(heartbeat_coro)

                    ok = await action_task
                    btw.stop()
                    heartbeat_task.cancel()
                    await monitor_task
                except BaseException:
                    btw.stop()
                    if heartbeat_task:
                        heartbeat_task.cancel()
                    # Ensure monitor_task is awaited to avoid "Task was destroyed" warning
                    if monitor_task and not monitor_task.done():
                        await monitor_task
                    raise
                console.print()

                if ok:
                    # Update status and inject as user message (don't mutate system prompt)
                    new_existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []

                    messages.append({
                        "role": "user",
                        "content": f"[操作已完成，项目状态已更新。当前已完成 {len(new_existing)} 章。]"
                    })

                    try:
                        with console.status("[dim]总结中...[/]", spinner="dots"):
                            resp2 = await provider.chat(messages, temperature=0.3, max_tokens=512)
                        messages.append({"role": "assistant", "content": resp2.content})
                    except Exception as e:
                        logger.warning(f"Post-action summary failed: {e}")

                # Truncate history to prevent context overflow
                messages[:] = _truncate_messages(messages)

            console.print()
    finally:
        await provider.close()
