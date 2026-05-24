"""Genre template loader."""

from __future__ import annotations

import json
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates" / "genres"


def list_genres() -> list[str]:
    """List available genre template names."""
    if not _TEMPLATES_DIR.exists():
        return []
    return sorted(p.stem for p in _TEMPLATES_DIR.glob("*.json"))


def load_genre(name: str) -> dict:
    """Load a genre template by name."""
    path = _TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到题材模板: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def is_literary_genre(genre: str) -> bool:
    """Check if a genre is literary fiction (not web novel)."""
    literary_keywords = [
        "纯文学", "严肃文学", "文学", "现实主义", "先锋", "乡土",
        "推理", "悬疑推理", "推理悬疑", "犯罪", "本格推理",
        "言情文学", "纯爱", "情感小说", "家庭伦理",
        "科幻文学", "硬科幻", "软科幻", "赛博朋克",
        "mystery_lit", "romance_lit", "scifi_lit", "literary",
    ]
    return any(kw in genre for kw in literary_keywords)


def resolve_genre_alias(name: str) -> str:
    """Resolve common genre aliases to canonical names."""
    aliases = {
        "玄幻": "xuanhuan",
        "修仙": "xianxia",
        "修真": "xianxia",
        "都市": "urban",
        "都市异能": "urban",
        "历史": "history",
        "科幻": "scifi",
        "奇幻": "fantasy",
        "悬疑": "mystery",
        "言情": "romance",
        # 文学类
        "纯文学": "literary",
        "严肃文学": "literary",
        "文学": "literary",
        "现实主义": "literary",
        "推理": "mystery_lit",
        "悬疑推理": "mystery_lit",
        "推理悬疑": "mystery_lit",
        "犯罪": "mystery_lit",
        "本格推理": "mystery_lit",
        "言情文学": "romance_lit",
        "纯爱": "romance_lit",
        "情感小说": "romance_lit",
        "家庭伦理": "romance_lit",
        "科幻文学": "scifi_lit",
        "硬科幻": "scifi_lit",
        "软科幻": "scifi_lit",
        "赛博朋克": "scifi_lit",
    }
    return aliases.get(name, name)
