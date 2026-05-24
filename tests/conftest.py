"""Test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with standard structure."""
    for d in [
        ".aznovel",
        ".aznovel/contracts",
        ".aznovel/commits",
        "设定集",
        "大纲",
        "正文",
        "审查报告",
    ]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path
