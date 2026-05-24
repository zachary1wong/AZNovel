"""Project initialization - conversational LLM-driven flow with outline iteration."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import typer

from aznovel.llm.base import LLMConfig
from aznovel.llm.provider_factory import create_provider
from aznovel.models.project import (
    ProtagonistState,
    ProjectInfo,
    ProjectState,
)
from aznovel.storage import project_fs
from aznovel.storage.state_store import StateStore
from aznovel.storage.template_loader import list_genres, load_genre, resolve_genre_alias
from aznovel.utils.rich_ui import console, error, info, panel, success, warn

# ── Phase 1: Parameter Collection ──────────────────────────────────────────

_COLLECT_SYSTEM_PROMPT = """你是一个专业的创作顾问，正在帮用户构思一部新作品。

你的任务是通过自然对话收集以下信息：
1. **作品类型**（必须首先确认）：网文、文学、短剧
2. 小说标题
3. 题材类型（根据作品类型选择：{genres}）
4. 主角姓名、身份/背景、目标/动机
5. 金手指/特殊能力（仅网文类需要，文学类和短剧不需要）
6. 故事的核心卖点或亮点
7. **写作规模**（必须询问）：
   - 总共打算写多少字
   - 每章/每集大约多少字

作品类型说明（必须先问清楚）：
- **网文**：玄幻、仙侠、都市、历史、奇幻、科幻 — 通常有金手指、升级、爽点，每章2000-3000字
- **文学**：纯文学、推理悬疑、言情文学、科幻文学 — 注重人物深度、文学性、思想性，无金手指，每章3000-5000字
- **短剧**：逆袭爽剧、甜宠、虐恋、复仇、穿越重生 — 强反转、快节奏、每集结尾有悬念，每集1500-2500字，剧本格式

额外能力：
- 如果用户提供了设定文件（txt/md），告诉他们可以用"导入设定"来导入
- 如果用户有一部分已写好的作品，告诉他们可以用"导入小说"来分析续写
- 如果用户有现成的大纲，告诉他们可以用"导入大纲"来导入

对话规则：
- 用轻松自然的中文交流，像朋友聊天一样
- **第一个问题必须问：你想写什么类型？网文、文学还是短剧？**
- 每次只问1-2个问题，不要一次性问太多
- 根据用户的回答追问细节，帮助他们完善想法
- 如果用户说"随便"或"你定"，给出合理的建议
- 如果用户选择文学类，不要问金手指相关问题
- 如果用户选择短剧，问清楚是哪种类型（逆袭/甜宠/虐恋/复仇等）
- **必须询问用户计划写的总字数和每章/每集字数**，这是关键参数
- 当你认为信息足够时，输出一个总结确认

当所有信息收集完毕后，在最后一段输出严格的JSON格式（不要包裹在代码块中）：
===PARAMS===
{{"title": "作品标题", "work_type": "网文/文学/短剧", "genre": "具体题材", "protagonist": "主角名", "identity": "身份", "goal": "目标", "golden_finger": "金手指（文学类和短剧填空字符串）", "selling_point": "核心卖点", "total_words": 1200000, "word_per_chapter": 2000, "import_settings": [], "import_novel": [], "import_outline": ""}}
===END===

注意：
- work_type: 必须是"网文"、"文学"或"短剧"之一，这是最重要的分类
- total_words: 总字数目标（必须询问用户，不要自己猜测）
- word_per_chapter: 每章/每集字数（必须询问用户，网文通常2000-3000字，文学类通常3000-5000字，短剧通常1500-2500字）
- target_chapters 和 chapters_per_volume 会根据 total_words 和 word_per_chapter 自动计算
- import_settings: 用户提供的设定文件路径列表（空列表表示没有）
- import_novel: 用户提供的已写作品文件路径列表（空列表表示没有）
- import_outline: 用户提供的大纲文件路径（空字符串表示没有）
- golden_finger: 文学类和短剧题材填空字符串""，不要填"无"
- 在输出JSON之前，先用自然语言总结你收集到的信息，请用户确认。"""


async def _conversational_collect(provider, progress_tracker=None) -> dict | None:
    """Phase 1: Collect init parameters via conversation."""
    genres = list_genres()
    system = _COLLECT_SYSTEM_PROMPT.format(genres="、".join(genres))

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    messages.append({
        "role": "assistant",
        "content": "你好！我是你的创作顾问。让我们一起来构思你的新作品吧！\n\n"
                   "首先，你想写什么类型的作品？\n"
                   "1. **网文** — 玄幻、仙侠、都市、历史等，有金手指、升级、爽点\n"
                   "2. **文学** — 纯文学、推理悬疑、言情文学等，注重深度和文学性\n"
                   "3. **短剧** — 逆袭爽剧、甜宠、虐恋、复仇等，强反转、快节奏\n\n"
                   "请告诉我你的选择（1/2/3 或直接说类型名称）："
    })
    console.print(f"\n[bold cyan]🤖 AZNovel 创作顾问[/]\n")
    console.print(messages[-1]["content"])
    console.print()

    max_turns = 20
    for turn in range(max_turns):
        # Pause progress bar during user input
        if progress_tracker:
            progress_tracker.pause()

        try:
            user_input = console.input("[bold green]你 > [/]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n已取消初始化。")
            return None

        # Resume progress bar after user input
        if progress_tracker:
            progress_tracker.resume()

        if not user_input.strip():
            continue

        if user_input.strip() in ("退出", "quit", "exit", "q"):
            console.print("已取消初始化。")
            return None

        messages.append({"role": "user", "content": user_input})

        resp = await provider.chat(messages, temperature=0.7, max_tokens=2048)
        reply = resp.content
        messages.append({"role": "assistant", "content": reply})

        if "===PARAMS===" in reply and "===END===" in reply:
            try:
                start = reply.index("===PARAMS===") + len("===PARAMS===")
                end = reply.index("===END===")
                params_json = reply[start:end].strip()
                params = json.loads(params_json)

                summary = reply[:reply.index("===PARAMS===")].strip()
                if summary:
                    console.print(f"\n[bold cyan]🤖 AZNovel 创作顾问[/]\n")
                    console.print(summary)

                # Pause progress bar for confirmation
                if progress_tracker:
                    progress_tracker.pause()

                console.print()
                confirm = console.input("[bold green]确认这些信息？(y/n) > [/]")
                if confirm.strip().lower() in ("y", "yes", "是", "好", "确认", ""):
                    return params
                else:
                    messages.append({"role": "user", "content": "不，我想修改一些信息。"})
                    continue
            except (json.JSONDecodeError, ValueError):
                pass

        console.print(f"\n[bold cyan]🤖 AZNovel 创作顾问[/]\n")
        console.print(reply)
        console.print()

    console.print("\n对话轮数已达上限。")
    return None


# ── Phase 2: File Import & Analysis ────────────────────────────────────────

async def _import_files(provider, params: dict) -> dict:
    """Import and analyze user-provided files. Returns enriched params."""
    from aznovel.core.analyzer import analyze_novel_text, analyze_settings_text

    settings_files = params.get("import_settings", [])
    novel_files = params.get("import_novel", [])
    outline_file = params.get("import_outline", "")

    # Import settings files
    settings_analysis = None
    if settings_files:
        all_settings_text = []
        for fpath in settings_files:
            p = Path(fpath).expanduser()
            if p.exists():
                text = p.read_text(encoding="utf-8")
                all_settings_text.append(f"=== {p.name} ===\n{text}")
                info(f"已读取设定文件: {p.name}")
            else:
                warn(f"文件不存在: {fpath}")

        if all_settings_text:
            combined = "\n\n".join(all_settings_text)
            console.print("[dim]正在分析设定文件...[/]")
            settings_analysis = await analyze_settings_text(provider, combined)
            if "error" not in settings_analysis:
                info("设定文件分析完成")
                # Merge settings into params
                if settings_analysis.get("title") and not params.get("title"):
                    params["title"] = settings_analysis["title"]
                if settings_analysis.get("genre") and not params.get("genre"):
                    params["genre"] = settings_analysis["genre"]
                if settings_analysis.get("protagonist", {}).get("name") and not params.get("protagonist"):
                    params["protagonist"] = settings_analysis["protagonist"]["name"]
                if settings_analysis.get("protagonist", {}).get("identity") and not params.get("identity"):
                    params["identity"] = settings_analysis["protagonist"]["identity"]
                if settings_analysis.get("protagonist", {}).get("goal") and not params.get("goal"):
                    params["goal"] = settings_analysis["protagonist"]["goal"]
                if settings_analysis.get("protagonist", {}).get("special_abilities") and not params.get("golden_finger"):
                    params["golden_finger"] = ", ".join(settings_analysis["protagonist"]["special_abilities"])
            else:
                warn(f"设定分析失败: {settings_analysis.get('error')}")

    # Import novel files
    novel_analysis = None
    if novel_files:
        all_novel_text = []
        for fpath in novel_files:
            p = Path(fpath).expanduser()
            if p.exists():
                text = p.read_text(encoding="utf-8")
                all_novel_text.append(text)
                info(f"已读取小说文件: {p.name} ({len(text)}字)")
            else:
                warn(f"文件不存在: {fpath}")

        if all_novel_text:
            combined = "\n\n".join(all_novel_text)
            console.print("[dim]正在分析已有小说内容...[/]")
            novel_analysis = await analyze_novel_text(provider, combined)
            if "error" not in novel_analysis:
                info("小说内容分析完成")
                params["novel_analysis"] = novel_analysis
                # Extract info from analysis
                if novel_analysis.get("title") and not params.get("title"):
                    params["title"] = novel_analysis["title"]
                if novel_analysis.get("genre") and not params.get("genre"):
                    params["genre"] = novel_analysis["genre"]
                if novel_analysis.get("protagonist", {}).get("name") and not params.get("protagonist"):
                    params["protagonist"] = novel_analysis["protagonist"]["name"]
            else:
                warn(f"小说分析失败: {novel_analysis.get('error')}")

    # Import outline
    if outline_file:
        p = Path(outline_file).expanduser()
        if p.exists():
            outline_text = p.read_text(encoding="utf-8")
            params["imported_outline"] = outline_text
            info(f"已读取大纲文件: {p.name}")
        else:
            warn(f"大纲文件不存在: {outline_file}")

    # Store analysis results for later use
    if settings_analysis:
        params["settings_analysis"] = settings_analysis
    if novel_analysis:
        params["novel_analysis"] = novel_analysis

    return params


# ── Phase 3: Outline Generation ────────────────────────────────────────────

async def _generate_outline_flow(provider, params: dict) -> dict | None:
    """Generate outline or use imported one. Returns outline dict."""
    from aznovel.core.analyzer import generate_outline

    # Check if user provided an outline file
    if params.get("imported_outline"):
        info("使用导入的大纲。")
        # Parse the imported outline as best we can
        outline_text = params["imported_outline"]
        # Ask LLM to structure it
        messages = [
            {"role": "system", "content": "你是一个小说大纲策划师。请将以下大纲文本转换为结构化JSON。"},
            {"role": "user", "content": f"请将以下大纲转换为JSON格式：\n\n{outline_text}\n\n"
             "输出JSON格式：{{\"master_outline\": \"总纲概述\", \"volumes\": [{{\"volume\": 1, \"title\": \"卷标题\", \"summary\": \"概述\", \"key_conflicts\": [], \"climax\": \"\", \"chapter_range\": \"\", \"chapters\": [{{\"chapter\": 1, \"title\": \"\", \"goal\": \"\", \"summary\": \"\"}}]}}]}}"},
        ]
        try:
            outline = await provider.chat_json(messages, temperature=0.3, max_tokens=8192)
            return outline
        except Exception as e:
            warn(f"大纲解析失败: {e}，将重新生成。")

    # Generate outline
    title = params.get("title", "未命名小说")
    genre = params.get("genre", "都市")
    protagonist = {
        "name": params.get("protagonist", ""),
        "identity": params.get("identity", ""),
        "goal": params.get("goal", ""),
        "golden_finger": params.get("golden_finger", ""),
    }

    # Build world setting from analysis if available
    world_setting = ""
    if params.get("settings_analysis"):
        sa = params["settings_analysis"]
        world_setting = sa.get("world_setting", "")
        if sa.get("power_system"):
            world_setting += f"\n力量体系: {sa['power_system']}"
        if sa.get("key_rules"):
            world_setting += "\n规则: " + "; ".join(sa["key_rules"])

    # Build existing summary from novel analysis
    existing_summary = ""
    if params.get("novel_analysis"):
        na = params["novel_analysis"]
        existing_summary = na.get("current_situation", "")
        if na.get("chapters_count"):
            existing_summary = f"已有{na['chapters_count']}章。" + existing_summary

    # Calculate from total_words and word_per_chapter
    total_words = params.get("total_words", 1200000)
    word_per_chapter = params.get("word_per_chapter", 2000)
    target_chapters = total_words // word_per_chapter
    chapters_per_volume = max(10, target_chapters // 10)

    console.print(f"\n[dim]正在生成大纲（{target_chapters}章，{target_chapters // chapters_per_volume}卷）...[/]")

    outline = await generate_outline(
        provider, title, genre, protagonist,
        world_setting=world_setting,
        existing_summary=existing_summary,
        target_chapters=target_chapters,
        chapters_per_volume=chapters_per_volume,
    )

    if "error" in outline:
        error(f"大纲生成失败: {outline['error']}")
        return None

    return outline


async def _outline_review_loop(provider, outline: dict, progress_tracker=None) -> dict | None:
    """Iterate on outline with user feedback until approved."""
    from aznovel.core.analyzer import revise_outline

    _display_outline(outline)

    max_iterations = 10
    for i in range(max_iterations):
        # Pause progress bar during user input
        if progress_tracker:
            progress_tracker.pause()

        console.print()
        user_input = console.input("[bold green]对大纲的意见（输入'通过'确认，或提出修改意见） > [/]")

        # Resume progress bar after user input
        if progress_tracker:
            progress_tracker.resume()

        if not user_input.strip():
            continue

        if user_input.strip() in ("通过", "ok", "approve", "确认", "y", "yes"):
            success("大纲已确认！")
            return outline

        if user_input.strip() in ("退出", "quit", "exit", "q"):
            console.print("已取消。")
            return None

        console.print("[dim]正在根据反馈修改大纲...[/]")
        outline = await revise_outline(provider, outline, user_input)

        if "error" in outline:
            error(f"大纲修改失败: {outline['error']}")
            continue

        _display_outline(outline)

    warn("已达最大修改次数，使用当前大纲。")
    return outline


def _display_outline(outline: dict) -> None:
    """Display outline in a readable format."""
    lines = []
    if outline.get("master_outline"):
        lines.append(f"[bold]总纲:[/]\n{outline['master_outline']}\n")

    for vol in outline.get("volumes", []):
        vol_num = vol.get("volume", "?")
        vol_title = vol.get("title", "")
        lines.append(f"[bold cyan]第{vol_num}卷: {vol_title}[/]")
        if vol.get("summary"):
            lines.append(f"  {vol['summary']}")
        if vol.get("key_conflicts"):
            lines.append(f"  冲突: {', '.join(vol['key_conflicts'])}")
        if vol.get("climax"):
            lines.append(f"  高潮: {vol['climax']}")

        # Show first volume's chapters in detail
        chapters = vol.get("chapters", [])
        if chapters and vol_num == 1:
            lines.append(f"  [dim]章节明细:[/]")
            for ch in chapters[:10]:  # Show first 10 chapters
                ch_num = ch.get("chapter", "?")
                ch_title = ch.get("title", "")
                ch_summary = ch.get("summary", "")
                lines.append(f"    第{ch_num}章 {ch_title}: {ch_summary}")
            if len(chapters) > 10:
                lines.append(f"    [dim]... 共{len(chapters)}章[/]")
        lines.append("")

    panel("小说大纲", "\n".join(lines))


# ── Phase 4: Project Creation ──────────────────────────────────────────────

def _create_project(
    project_dir: Path,
    title: str,
    genre_input: str,
    prot_name: str,
    prot_cultivation: str,
    prot_goal: str,
    golden_finger: str,
    selling_point: str,
    outline: dict | None = None,
    settings_analysis: dict | None = None,
    novel_analysis: dict | None = None,
    imported_settings_files: list[str] | None = None,
    imported_novel_files: list[str] | None = None,
    target_chapters: int = 600,
    chapters_per_volume: int = 50,
) -> None:
    """Create the project with all collected parameters and approved outline."""
    genre_key = resolve_genre_alias(genre_input)

    info(f"创建项目: {project_dir}")
    project_fs.ensure_project_dirs(project_dir)

    # Load genre template
    try:
        genre_template = load_genre(genre_key)
    except FileNotFoundError:
        warn(f"未找到题材模板 '{genre_key}'，使用默认设置")
        genre_template = {}

    # Build state
    state = ProjectState(
        project_info=ProjectInfo(
            title=title,
            genre=genre_input,
            target_chapters=target_chapters,
            chapters_per_volume=chapters_per_volume,
            created_at=datetime.now().isoformat(),
        ),
        protagonist=ProtagonistState(
            name=prot_name,
            cultivation=prot_cultivation,
            current_goal=prot_goal,
            special_abilities=[golden_finger] if golden_finger else [],
        ),
    )

    # If we have novel analysis, update state with existing progress
    if novel_analysis:
        chapters_count = novel_analysis.get("chapters_count", 0)
        if chapters_count > 0:
            state.progress.current_chapter = chapters_count
            info(f"检测到已有{chapters_count}章内容，将从第{chapters_count + 1}章继续写作。")

        # Add known characters
        if novel_analysis.get("characters"):
            from aznovel.models.project import EntityRecord
            for char in novel_analysis["characters"]:
                state.entities.append(EntityRecord(
                    name=char.get("name", ""),
                    type="character",
                    first_appearance=1,
                    state={"description": char.get("identity", "")},
                ))

        # Add plot threads
        if novel_analysis.get("plot_threads"):
            from aznovel.models.project import PlotThread
            for pt in novel_analysis["plot_threads"]:
                state.plot_threads.append(PlotThread(
                    name=pt.get("name", ""),
                    status=pt.get("status", "active"),
                    summary=pt.get("summary", ""),
                ))

    # Save state
    store = StateStore(project_dir)
    store.save(state)

    # Save master setting
    from aznovel.core.contract_manager import ContractManager

    mgr = ContractManager(project_dir)
    master = mgr.generate_master_setting(state, genre_template)
    master.golden_finger = golden_finger
    if selling_point:
        master.satisfaction_points.insert(0, selling_point)

    # Merge settings analysis into master setting
    if settings_analysis:
        if settings_analysis.get("world_setting"):
            master.world_rules.insert(0, settings_analysis["world_setting"])
        if settings_analysis.get("conflict"):
            master.satisfaction_points.insert(0, settings_analysis["conflict"])
        if settings_analysis.get("key_rules"):
            master.anti_patterns = [r for r in settings_analysis.get("key_rules", []) if "不要" in r or "禁止" in r]

    mgr.save_master_setting(master)

    # Generate settings files
    if not imported_settings_files:
        from aznovel.storage.template_loader import is_literary_genre
        is_lit = is_literary_genre(genre_input)
        _write_setting_file(project_dir, "世界观.md", _world_template(title, genre_template))
        _write_setting_file(project_dir, "主角卡.md", _protagonist_template(prot_name, prot_cultivation, prot_goal, golden_finger, is_lit))
    else:
        # Copy imported settings
        for fpath in imported_settings_files:
            p = Path(fpath).expanduser()
            if p.exists():
                dest = project_dir / "设定集" / p.name
                if not dest.exists():
                    dest.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
                    info(f"已复制设定文件: {p.name}")

    # Copy imported novel files
    if imported_novel_files:
        for fpath in imported_novel_files:
            p = Path(fpath).expanduser()
            if p.exists():
                dest = project_dir / "正文" / p.name
                if not dest.exists():
                    dest.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
                    info(f"已复制小说文件: {p.name}")

    # Save outline
    if outline:
        _save_outline(project_dir, title, outline)
    else:
        _write_outline_skeleton(project_dir, title, target_chapters, chapters_per_volume)

    # Create project config
    project_fs.save_json(
        project_dir / ".aznovel" / "config.json",
        {"provider": "", "model": "", "api_key": "", "base_url": ""},
    )

    # Display project structure
    panel("项目结构", f"""
{project_dir}/
├── .aznovel/          # 项目内部数据
├── 设定集/            # 世界观、人物设定
├── 大纲/              # 故事大纲
├── 正文/              # 章节正文
└── 审查报告/          # 审查报告
""")

    success(f"项目 '{title}' 初始化完成！")

    next_chapter = state.progress.current_chapter + 1
    info(f"\n下一步:")
    info(f"  cd {project_dir}")
    if next_chapter > 1:
        info(f"  aznovel write --chapter {next_chapter}  # 继续写作第{next_chapter}章")
    else:
        info(f"  aznovel write --chapter 1  # 开始写作")


# ── Outline Save ────────────────────────────────────────────────────────────

def _save_outline(root: Path, title: str, outline: dict) -> None:
    """Save outline as structured JSON and readable markdown."""
    import json as json_mod

    # Save JSON version
    json_path = root / "大纲" / "outline.json"
    json_path.write_text(json_mod.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")

    # Save markdown version
    lines = [f"# {title} - 总纲\n"]

    if outline.get("master_outline"):
        lines.append(f"\n## 总纲概述\n{outline['master_outline']}\n")

    for vol in outline.get("volumes", []):
        vol_num = vol.get("volume", "?")
        vol_title = vol.get("title", "")
        lines.append(f"\n## 第{vol_num}卷: {vol_title}\n")

        if vol.get("summary"):
            lines.append(f"**概述**: {vol['summary']}\n")
        if vol.get("key_conflicts"):
            lines.append(f"**核心冲突**: {', '.join(vol['key_conflicts'])}\n")
        if vol.get("climax"):
            lines.append(f"**高潮**: {vol['climax']}\n")
        if vol.get("chapter_range"):
            lines.append(f"**章节范围**: {vol['chapter_range']}\n")

        chapters = vol.get("chapters", [])
        if chapters:
            lines.append("### 章节明细\n")
            for ch in chapters:
                ch_num = ch.get("chapter", "?")
                ch_title = ch.get("title", "")
                ch_goal = ch.get("goal", "")
                ch_summary = ch.get("summary", "")
                lines.append(f"- **第{ch_num}章 {ch_title}**: {ch_summary}")
                if ch_goal:
                    lines.append(f"  - 目标: {ch_goal}")
            lines.append("")

    md_path = root / "大纲" / "总纲.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    info("大纲已保存: 大纲/总纲.md, 大纲/outline.json")


# ── Template Helpers ────────────────────────────────────────────────────────

def _write_setting_file(root: Path, name: str, content: str) -> None:
    path = root / "设定集" / name
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _write_outline_skeleton(root: Path, title: str, target: int, per_vol: int) -> None:
    path = root / "大纲" / "总纲.md"
    if path.exists():
        return
    volumes = target // per_vol
    lines = [f"# {title} - 总纲\n"]
    for v in range(1, min(volumes + 1, 11)):
        lines.append(f"\n## 第{v}卷 (第{(v-1)*per_vol+1}-{v*per_vol}章)\n")
        lines.append(f"- 卷目标: [待填]")
        lines.append(f"- 核心冲突: [待填]")
        lines.append(f"- 高潮节点: [待填]")
    path.write_text("\n".join(lines), encoding="utf-8")


def _world_template(title: str, genre_template: dict) -> str:
    lines = [f"# {title} - 世界观设定\n"]
    if genre_template.get("world_building"):
        wb = genre_template["world_building"]
        if isinstance(wb, dict):
            for key, val in wb.items():
                if isinstance(val, list):
                    lines.append(f"\n## {key}")
                    for item in val:
                        lines.append(f"- {item}")
                elif isinstance(val, str):
                    lines.append(f"\n## {key}\n{val}")
    if genre_template.get("power_system_template"):
        ps = genre_template["power_system_template"]
        lines.append("\n## 力量体系")
        if "realms" in ps:
            lines.append(f"\n境界: {' → '.join(ps['realms'])}")
        if "rules" in ps:
            for rule in ps["rules"]:
                lines.append(f"- {rule}")
    lines.append("\n## [待补充]")
    return "\n".join(lines)


def _protagonist_template(name: str, cultivation: str, goal: str, golden_finger: str, is_literary: bool = False) -> str:
    lines = [f"# 主角卡 - {name or '[待填]'}\n"]
    lines.append(f"- 姓名: {name or '[待填]'}")
    if is_literary:
        lines.append(f"- 身份/职业: {cultivation or '[待填]'}")
        lines.append(f"- 核心动机: {goal or '[待填]'}")
    else:
        lines.append(f"- 初始境界/身份: {cultivation or '[待填]'}")
        lines.append(f"- 初始目标: {goal or '[待填]'}")
        lines.append(f"- 金手指: {golden_finger or '[待填]'}")
    lines.append(f"\n## 性格特点\n[待填]")
    lines.append(f"\n## 人物背景\n[待填]")
    if is_literary:
        lines.append(f"\n## 人物弧光\n[待填]")
        lines.append(f"\n## 内心矛盾\n[待填]")
    return "\n".join(lines)


# ── Entry Point ─────────────────────────────────────────────────────────────

def run_init(
    directory: str,
    title: str | None,
    genre: str | None,
    prot_name: str | None = None,
    prot_cultivation: str | None = None,
    prot_goal: str | None = None,
    golden_finger: str | None = None,
    llm_profile: dict | None = None,
    progress_tracker=None,
) -> None:
    """Project initialization - conversational or direct mode."""
    project_dir = Path(directory).resolve()

    # If all key params provided, do direct init (non-interactive)
    if title and genre and prot_name:
        _direct_init(project_dir, title, genre, prot_name, prot_cultivation, prot_goal, golden_finger)
        if progress_tracker:
            progress_tracker.finish()
        return

    # Otherwise, enter conversational mode with full flow
    _conversational_init_flow(project_dir, llm_profile=llm_profile, progress_tracker=progress_tracker)


def _direct_init(
    project_dir: Path,
    title: str,
    genre: str,
    prot_name: str,
    prot_cultivation: str | None,
    prot_goal: str | None,
    golden_finger: str | None,
) -> None:
    """Direct init with all params provided via CLI (no outline generation)."""
    info("=== AZNovel 项目初始化 ===\n")
    _create_project(
        project_dir, title, genre, prot_name,
        prot_cultivation or "", prot_goal or "", golden_finger or "", ""
    )


def _conversational_init_flow(project_dir: Path, llm_profile: dict | None = None, progress_tracker=None) -> None:
    """Full conversational init: collect → import → outline → review → create."""
    from aznovel.cli.config_cmd import load_config

    info("=== AZNovel 创作顾问 ===\n")
    info("让我来帮你构思一部新小说！\n")

    config_data = load_config()
    if not config_data.get("api_key"):
        error("未设置 API Key。请先运行: aznovel config set api_key YOUR_KEY")
        raise typer.Exit(1)

    llm_config = LLMConfig(
        provider=config_data["provider"],
        model=config_data["model"],
        api_key=config_data["api_key"],
        base_url=config_data.get("base_url", ""),
        temperature=config_data.get("temperature", 0.7),
        max_tokens=config_data.get("max_tokens", 4096),
    )

    provider = create_provider(llm_config)

    async def _run():
        try:
            # Phase 1: Collect parameters
            params = await _conversational_collect(provider, progress_tracker)
            if params is None:
                return None
            if progress_tracker:
                progress_tracker.next("参数收集")

            # Phase 2: Import files if provided
            has_files = (
                params.get("import_settings")
                or params.get("import_novel")
                or params.get("import_outline")
            )
            if has_files:
                console.print("\n[bold]正在导入和分析文件...[/]\n")
                params = await _import_files(provider, params)
            if progress_tracker:
                progress_tracker.next("文件分析")

            # Phase 3: Generate or import outline
            console.print("\n[bold]正在准备大纲...[/]\n")
            outline = await _generate_outline_flow(provider, params)
            if outline is None:
                warn("大纲生成失败，将使用空白大纲。")
            if progress_tracker:
                progress_tracker.next("大纲生成")

            # Phase 4: Review outline with user
            if outline:
                confirmed_outline = await _outline_review_loop(provider, outline, progress_tracker)
                if confirmed_outline is None:
                    return None
            else:
                confirmed_outline = None
            if progress_tracker:
                progress_tracker.next("大纲审核")

            return {
                "params": params,
                "outline": confirmed_outline,
            }

        finally:
            await provider.close()

    try:
        result = asyncio.run(_run())
    except Exception as e:
        error(f"初始化出错: {e}")
        raise typer.Exit(1)

    if result is None:
        error("初始化取消。")
        raise typer.Exit(1)

    params = result["params"]
    outline = result["outline"]

    # Calculate target_chapters from total_words and word_per_chapter
    total_words = params.get("total_words", 1200000)
    word_per_chapter = params.get("word_per_chapter", 2000)
    target_chapters = total_words // word_per_chapter
    chapters_per_volume = max(10, target_chapters // 10)  # 默认分10卷

    # Determine genre based on work_type
    work_type = params.get("work_type", "")
    genre = params.get("genre", "")
    if work_type == "短剧":
        # Map short drama sub-genres
        drama_genre_map = {
            "逆袭": "逆袭爽剧", "爽剧": "逆袭爽剧",
            "甜宠": "甜宠剧", "甜宠剧": "甜宠剧",
            "虐恋": "虐恋剧", "虐恋剧": "虐恋剧",
            "复仇": "复仇剧", "复仇剧": "复仇剧",
            "穿越": "穿越重生", "重生": "穿越重生",
            "都市": "都市情感", "都市情感": "都市情感",
            "古装": "古装剧", "古装剧": "古装剧",
        }
        genre = drama_genre_map.get(genre, "短剧")
    elif not genre:
        genre = "都市"

    console.print(f"\n[bold]正在创建项目...[/]\n")

    _create_project(
        project_dir,
        title=params.get("title", "未命名作品"),
        genre_input=genre,
        prot_name=params.get("protagonist", ""),
        prot_cultivation=params.get("identity", ""),
        prot_goal=params.get("goal", ""),
        golden_finger=params.get("golden_finger", ""),
        selling_point=params.get("selling_point", ""),
        outline=outline,
        settings_analysis=params.get("settings_analysis"),
        novel_analysis=params.get("novel_analysis"),
        imported_settings_files=params.get("import_settings"),
        imported_novel_files=params.get("import_novel"),
        target_chapters=target_chapters,
        chapters_per_volume=chapters_per_volume,
    )

    # Save word_per_chapter to project config for later use
    project_fs.save_json(
        project_dir / ".aznovel" / "config.json",
        {"word_target": word_per_chapter},
    )

    # Save LLM profile to project config
    if llm_profile:
        from aznovel.cli.config_cmd import apply_profile_to_config
        apply_profile_to_config(llm_profile, project_dir / ".aznovel" / "config.json")
        info(f"LLM 配置 '{llm_profile.get('name', '')}' 已写入项目配置。")

    if progress_tracker:
        progress_tracker.next("项目创建")
