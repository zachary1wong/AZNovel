"""Polish - batch language polishing for chapters."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aznovel.llm.base import LLMProvider
from aznovel.utils.rich_ui import console

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10  # paragraphs per LLM call

_POLISH_PROMPT = """你是一个极其保守的中文文字编辑。你只修复明确的错误，绝不润色或改写。

只修以下问题（有才改，没有就原样返回）：
1. 明确的语病：句子成分残缺、搭配不当、语序错误导致读不懂
2. 明确的逻辑错误：因果关系不通、前后矛盾、条件缺失
   例如："再扣你工钱"缺少条件 → 应为"再耽误就扣你工钱"
3. 明确的用词错误：如"反映"写成"反应"这类确定性错误，或"红木"写成"竹板"这种前后不一致

绝对不做的事（违反任何一条都不合格）：
- 不改同义词、近义词（如"埋下去"→"低下去"，两个都对，不改）
- 不改句式结构（如"愣了下"→"愣了一下"，都对，不改）
- 不改语气词、标点风格
- 不改描写手法、修辞方式
- 不润色、不优化、不"让文字更好"
- 如果不确定是不是错误，就不改

输入格式：每段用 ---PARA_N--- 标记（N是段落编号）。
输出格式：同样用 ---PARA_N--- 标记每段。只输出需要修改的段落，没发现问题的段落不要输出。
绝对不要在段落内容后加注释、说明、括号备注。只返回纯文本。
如果所有段落都没问题，输出：无修改"""


def _split_paragraphs(text: str) -> list[str]:
    """Split chapter text into paragraphs by double newline."""
    return text.split("\n\n")


def _show_diff(para_idx: int, original: str, polished: str) -> None:
    """Display before→after for a changed paragraph."""
    max_len = 200
    orig_display = original[:max_len] + "..." if len(original) > max_len else original
    polished_display = polished[:max_len] + "..." if len(polished) > max_len else polished

    console.print(f"\n[bold cyan]段落 {para_idx + 1}:[/]")
    console.print(f"  [dim]原文:[/] {orig_display}")
    console.print(f"  [bold green]修改:[/] {polished_display}")


def _format_batch(paragraphs: list[str], indices: list[int]) -> str:
    """Format a batch of paragraphs for the LLM."""
    parts = []
    for idx, para in zip(indices, paragraphs):
        parts.append(f"---PARA_{idx}---\n{para}")
    return "\n\n".join(parts)


def _parse_batch_response(response: str, expected_indices: list[int]) -> dict[int, str]:
    """Parse LLM response to extract modified paragraphs.

    Returns dict mapping paragraph index to polished text.
    """
    if "无修改" in response and "---PARA_" not in response:
        return {}

    result = {}
    import re
    # Split by ---PARA_N--- markers
    pattern = r"---PARA_(\d+)---"
    parts = re.split(pattern, response)
    # parts[0] is before first marker (usually empty), then alternating: index, content
    for i in range(1, len(parts) - 1, 2):
        try:
            idx = int(parts[i])
            content = parts[i + 1].strip()
            # Strip LLM notes/annotations like （注：...）
            content = re.sub(r"（注：[^）]*）", "", content).strip()
            # Skip if content is empty or just says "无修改"
            if content and "无修改" not in content:
                result[idx] = content
        except (ValueError, IndexError):
            continue
    return result


async def _polish_batch(provider: LLMProvider, paragraphs: list[str], indices: list[int]) -> dict[int, str]:
    """Polish a batch of paragraphs via LLM.

    Returns dict mapping paragraph index to polished text (only changed ones).
    """
    batch_text = _format_batch(paragraphs, indices)
    messages = [
        {"role": "system", "content": _POLISH_PROMPT},
        {"role": "user", "content": batch_text},
    ]
    result = await provider.chat(messages, temperature=0.1, max_tokens=4096)
    return _parse_batch_response(result.content, indices)


async def _run_polish_inner(
    provider: LLMProvider,
    root: Path,
    chapter: int,
    on_step=None,
    auto_save: bool = False,
    batch_size: int = _BATCH_SIZE,
) -> bool:
    """Core polish logic for a single chapter.

    Returns True if any changes were made and saved.
    """
    from aznovel.storage import project_fs
    from aznovel.utils.rich_ui import info, success, warn, error

    paths = project_fs.project_paths(root)
    chapters_dir = paths["chapters_dir"]
    ch_path = chapters_dir / f"第{chapter:03d}章.md"

    if not ch_path.exists():
        error(f"第{chapter:03d}章不存在")
        return False

    text = ch_path.read_text(encoding="utf-8")
    paragraphs = _split_paragraphs(text)

    if not paragraphs:
        warn(f"第{chapter}章内容为空")
        return False

    info(f"精修第{chapter}章（{len(paragraphs)} 个段落）")

    # Build batches: skip short/title paragraphs, batch the rest
    batches: list[list[tuple[int, str]]] = []
    current_batch: list[tuple[int, str]] = []

    for i, para in enumerate(paragraphs):
        stripped = para.strip()
        # Skip short paragraphs and title lines
        if len(stripped) < 20 or stripped.startswith("# 第"):
            continue
        current_batch.append((i, para))
        if len(current_batch) >= batch_size:
            batches.append(current_batch)
            current_batch = []
    if current_batch:
        batches.append(current_batch)

    if not batches:
        info(f"第{chapter}章没有需要精修的段落。")
        return False

    # Process each batch
    changed_map: dict[int, str] = {}  # para_idx -> polished text
    total_batches = len(batches)

    for batch_idx, batch in enumerate(batches):
        if on_step:
            on_step(f"精修第{chapter}章 批次 {batch_idx + 1}/{total_batches}")

        indices = [b[0] for b in batch]
        para_texts = [b[1] for b in batch]

        try:
            changes = await _polish_batch(provider, para_texts, indices)
        except Exception as e:
            logger.error(f"Polish batch {batch_idx} failed: {e}")
            continue

        # Filter: only keep changes that actually differ from original
        for idx, polished in changes.items():
            original = paragraphs[idx]
            orig_norm = " ".join(original.split())
            pol_norm = " ".join(polished.split())
            if pol_norm != orig_norm:
                changed_map[idx] = polished

    if not changed_map:
        info(f"第{chapter}章没有需要修改的段落。")
        return False

    # Show diffs
    for idx in sorted(changed_map.keys()):
        _show_diff(idx, paragraphs[idx], changed_map[idx])

    # Build polished paragraphs
    polished_paragraphs = []
    for i, para in enumerate(paragraphs):
        if i in changed_map:
            polished_paragraphs.append(changed_map[i])
        else:
            polished_paragraphs.append(para)

    changed_count = len(changed_map)
    console.print(f"\n[bold]共修改 {changed_count} 个段落[/]")

    if auto_save:
        info("自动保存模式，直接保存。")
    else:
        confirm = input("\001\033[1;32m\002是否保存修改？(y/n) > \001\033[0m\002")
        if confirm.strip().lower() not in ("y", "yes", "是", "好", "确认", ""):
            info("已取消保存。")
            return False

    # Save polished content
    polished_text = "\n\n".join(polished_paragraphs)
    ch_path.write_text(polished_text, encoding="utf-8")
    success(f"第{chapter}章已精修并保存！")
    return True


def run_polish(
    chapter: int | None = None,
    start: int | None = None,
    end: int | None = None,
    all_chapters: bool = False,
    careful: bool = False,
    profile_name: str | None = None,
) -> None:
    """CLI entry point for polish command."""
    from aznovel.cli.config_cmd import build_llm_config
    from aznovel.llm.provider_factory import create_provider
    from aznovel.storage.project_fs import require_project_root, project_paths
    from aznovel.utils.rich_ui import error, info

    root = require_project_root()
    paths = project_paths(root)
    chapters_dir = paths["chapters_dir"]

    if not chapters_dir.exists():
        error("还没有任何章节")
        return

    # Determine which chapters to polish
    chapter_files = sorted(chapters_dir.glob("第*章.md"))
    if not chapter_files:
        error("还没有任何章节")
        return

    from aznovel.utils.text import extract_chapter_number

    all_nums = []
    for f in chapter_files:
        num = extract_chapter_number(f.name)
        if num:
            all_nums.append(num)

    if all_chapters:
        target_chapters = all_nums
    elif chapter is not None:
        if chapter not in all_nums:
            error(f"第{chapter:03d}章不存在")
            return
        target_chapters = [chapter]
    elif start is not None and end is not None:
        target_chapters = [n for n in all_nums if start <= n <= end]
        if not target_chapters:
            error(f"第{start}-{end}章范围内没有章节")
            return
    else:
        error("请指定章节：-c N（单章）、-s N -e M（范围）、--all（全部）")
        return

    info(f"将精修 {len(target_chapters)} 章：{', '.join(f'第{n}章' for n in target_chapters)}")

    llm_config = build_llm_config(profile_name)
    provider = create_provider(llm_config)

    # Auto-save when polishing multiple chapters (range or all)
    auto_save = all_chapters or (start is not None and end is not None)
    batch_size = 1 if careful else _BATCH_SIZE

    async def _run():
        try:
            success_count = 0
            for ch_num in target_chapters:
                console.print(f"\n{'=' * 40}")
                ok = await _run_polish_inner(provider, root, ch_num, auto_save=auto_save, batch_size=batch_size)
                if ok:
                    success_count += 1
            console.print(f"\n{'=' * 40}")
            info(f"精修完成！修改了 {success_count}/{len(target_chapters)} 章。")
        finally:
            await provider.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n精修已中断。")
