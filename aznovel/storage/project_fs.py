"""Project filesystem operations."""

from __future__ import annotations

import json
from pathlib import Path

# Standard project directory names
AZNOVEL_DIR = ".aznovel"
CONTRACTS_DIR = "contracts"
COMMITS_DIR = "commits"
SETTINGS_DIR = "设定集"
OUTLINE_DIR = "大纲"
CHAPTERS_DIR = "正文"
REVIEWS_DIR = "审查报告"

# Standard files
STATE_FILE = "state.json"
CONFIG_FILE = "config.json"
MASTER_SETTING_FILE = "master_setting.json"


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from start (or CWD) looking for .aznovel/state.json."""
    current = start or Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / AZNOVEL_DIR / STATE_FILE).exists():
            return parent
    return None


def require_project_root() -> Path:
    """Find project root or raise."""
    root = find_project_root()
    if root is None:
        raise RuntimeError(
            "未找到 AZNovel 项目。请先在项目目录运行 'aznovel init'"
        )
    return root


def ensure_project_dirs(root: Path) -> None:
    """Create all standard project directories."""
    for d in [
        Path(AZNOVEL_DIR),
        Path(AZNOVEL_DIR) / CONTRACTS_DIR,
        Path(AZNOVEL_DIR) / COMMITS_DIR,
        Path(SETTINGS_DIR),
        Path(OUTLINE_DIR),
        Path(CHAPTERS_DIR),
        Path(REVIEWS_DIR),
    ]:
        (root / d).mkdir(parents=True, exist_ok=True)


def project_paths(root: Path) -> dict[str, Path]:
    """Return all standard paths for a project."""
    az = Path(AZNOVEL_DIR)
    return {
        "root": root,
        "aznovel_dir": root / az,
        "state_file": root / az / STATE_FILE,
        "config_file": root / az / CONFIG_FILE,
        "contracts_dir": root / az / CONTRACTS_DIR,
        "commits_dir": root / az / COMMITS_DIR,
        "settings_dir": root / Path(SETTINGS_DIR),
        "outline_dir": root / Path(OUTLINE_DIR),
        "chapters_dir": root / Path(CHAPTERS_DIR),
        "reviews_dir": root / Path(REVIEWS_DIR),
    }


def load_json(path: Path) -> dict:
    """Load a JSON file, return empty dict if missing."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    """Save data as JSON with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
