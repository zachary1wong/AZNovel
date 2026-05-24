"""Rich terminal UI utilities."""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

console = Console()


def info(msg: str) -> None:
    console.print(f"[bold blue]▸[/] {msg}")


def success(msg: str) -> None:
    console.print(f"[bold green]✓[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"[bold yellow]⚠[/] {msg}")


def error(msg: str) -> None:
    console.print(f"[bold red]✗[/] {msg}")


def panel(title: str, content: str, *, border_style: str = "blue") -> None:
    console.print(Panel(content, title=title, border_style=border_style))


def make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    )


def status_table(rows: list[tuple[str, str]], title: str = "状态") -> None:
    table = Table(title=title, show_header=False, box=None)
    table.add_column("键", style="bold")
    table.add_column("值")
    for key, val in rows:
        table.add_row(key, val)
    console.print(table)


# ── Progress Tracker ────────────────────────────────────────────────────────

class ProgressTracker:
    """Simple step-based progress tracker for multi-step workflows.

    Prints a status line at each step instead of using Live refresh,
    so it doesn't interfere with user input.
    """

    def __init__(self, phases: list[str]) -> None:
        self._phases = phases
        self._total = len(phases)
        self._current = 0
        self._start_time = time.time()

    def next(self, description: str | None = None) -> None:
        """Advance to next phase and print status."""
        self._current += 1
        phase = description or (self._phases[self._current - 1] if self._current <= self._total else "完成")
        elapsed = time.time() - self._start_time

        # Calculate ETA
        if self._current > 0:
            per_phase = elapsed / self._current
            remaining = per_phase * (self._total - self._current)
            if remaining < 60:
                eta = f"{int(remaining)}秒"
            else:
                eta = f"{int(remaining // 60)}分{int(remaining % 60)}秒"
        else:
            eta = "计算中..."

        # Build progress bar
        pct = int(self._current / self._total * 100)
        bar_width = 20
        filled = int(bar_width * self._current / self._total)
        bar = "█" * filled + "░" * (bar_width - filled)

        console.print(f"[bold cyan]进度[/] {bar} {pct:>3d}% ({self._current}/{self._total}) [dim]{phase}[/] [dim]剩余{eta}[/]")

    def finish(self) -> None:
        """Print completion status."""
        elapsed = time.time() - self._start_time
        if elapsed < 60:
            time_str = f"{int(elapsed)}秒"
        else:
            time_str = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"
        console.print(f"[bold green]完成[/] {'█' * 20} 100% ({self._total}/{self._total}) [dim]耗时{time_str}[/]")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.finish()


# ── /btw Non-blocking Monitor ──────────────────────────────────────────────

class BtwMonitor:
    """Background stdin monitor for /btw commands during long-running actions."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._thread: threading.Thread | None = None
        self._active = False
        self._current_step = ""
        self._start_time = time.time()

    def start(self) -> None:
        """Start background stdin reader thread."""
        self._active = True
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background thread."""
        self._active = False

    def set_step(self, step: str) -> None:
        """Update current pipeline step (called from pipeline)."""
        self._current_step = step

    def _reader(self) -> None:
        """Background thread: read stdin, queue /btw commands."""
        while self._active:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith("/btw"):
                    self._queue.put_nowait(line)
                # Non-/btw input is silently ignored during action
            except (EOFError, OSError):
                break

    async def monitor_loop(self) -> None:
        """Async loop: process queued /btw commands until stopped."""
        while self._active or not self._queue.empty():
            try:
                line = await asyncio.wait_for(self._queue.get(), timeout=0.3)
                self._handle(line)
            except asyncio.TimeoutError:
                continue

    def _handle(self, line: str) -> None:
        """Process a /btw command and print the result."""
        parts = line.split(maxsplit=2)
        cmd = parts[1] if len(parts) > 1 else ""

        if cmd == "status":
            self._show_status()
        elif cmd == "progress":
            self._show_progress()
        elif cmd == "chapter":
            num = parts[2].strip() if len(parts) > 2 else ""
            self._show_chapter(num)
        else:
            self._show_help()

    def _show_help(self) -> None:
        console.print("\n[bold cyan]── /btw 命令 ──[/]")
        console.print("  /btw status    — 项目状态")
        console.print("  /btw progress  — 当前执行步骤")
        console.print("  /btw chapter N — 查看第N章摘要")
        console.print("  /btw           — 显示此帮助\n")

    def _show_status(self) -> None:
        from aznovel.storage.state_store import StateStore
        from aznovel.storage import project_fs

        store = StateStore(self._root)
        state = store.load()
        paths = project_fs.project_paths(self._root)
        chapters_dir = paths["chapters_dir"]
        existing = sorted(chapters_dir.glob("第*章.md")) if chapters_dir.exists() else []

        elapsed = int(time.time() - self._start_time)
        console.print(f"\n[bold cyan]── 项目状态 ──[/]")
        console.print(f"  小说: {state.project_info.title}")
        console.print(f"  已完成: {len(existing)} 章 / 目标 {state.project_info.target_chapters} 章")
        console.print(f"  主角: {state.protagonist.name}")
        console.print(f"  本次操作已耗时: {elapsed}秒")
        console.print()

    def _show_progress(self) -> None:
        elapsed = int(time.time() - self._start_time)
        console.print(f"\n[bold cyan]── 当前进度 ──[/]")
        console.print(f"  步骤: {self._current_step or '准备中...'}")
        console.print(f"  已耗时: {elapsed}秒")
        console.print()

    def _show_chapter(self, num_str: str) -> None:
        from aznovel.storage import project_fs
        from aznovel.utils.text import extract_chapter_number

        if not num_str:
            console.print("\n[bold yellow]用法: /btw chapter N[/]\n")
            return

        try:
            num = int(num_str)
        except ValueError:
            console.print("\n[bold yellow]章节号必须是数字[/]\n")
            return

        paths = project_fs.project_paths(self._root)
        path = paths["chapters_dir"] / f"第{num:03d}章.md"
        if not path.exists():
            console.print(f"\n[bold yellow]第{num}章不存在[/]\n")
            return

        text = path.read_text(encoding="utf-8")
        preview = text[:500]
        if len(text) > 500:
            preview += "\n... (已截断)"
        console.print(f"\n[bold cyan]── 第{num}章预览 ──[/]")
        console.print(preview)
        console.print()
