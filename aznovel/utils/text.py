"""Text utility functions."""

from __future__ import annotations

import re


def count_chinese_chars(text: str) -> int:
    """Count Chinese characters in text."""
    return len(re.findall(r"[一-鿿]", text))


def count_words(text: str) -> int:
    """Count words (Chinese chars + English words)."""
    chinese = count_chinese_chars(text)
    no_chinese = re.sub(r"[一-鿿]", " ", text)
    english = len(no_chinese.split())
    return chinese + english


def extract_chapter_number(filename: str) -> int | None:
    """Extract chapter number from filename like '第001章.md'."""
    m = re.search(r"第(\d+)章", filename)
    return int(m.group(1)) if m else None


def chapter_filename(n: int) -> str:
    """Generate standard chapter filename."""
    return f"第{n:03d}章.md"
