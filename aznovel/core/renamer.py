"""Controlled character renaming across an AZNovel project."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from pathlib import Path

from aznovel.llm.base import LLMProvider
from aznovel.storage import project_fs
from aznovel.storage.state_store import StateStore
from aznovel.utils.rich_ui import error, info, success, warn


_TEXT_SUFFIXES = {".md", ".json", ".txt"}
_RELATIONSHIP_TERMS = {
    "爸爸",
    "妈妈",
    "父亲",
    "母亲",
    "儿子",
    "女儿",
    "孩子",
    "老婆",
    "丈夫",
    "妻子",
    "哥哥",
    "姐姐",
    "弟弟",
    "妹妹",
    "老师",
    "教授",
    "老板",
    "医生",
}
_TITLE_SUFFIXES = (
    "教授",
    "博士",
    "院士",
    "老师",
    "先生",
    "女士",
    "主任",
    "所长",
    "主管",
    "经理",
    "总监",
    "董事",
    "董事长",
    "总",
    "董",
    "工",
)


@dataclass
class RenameMapping:
    """One exact old/new rename pair."""

    old: str
    new: str
    reason: str = ""
    source: str = "auto"


@dataclass
class RenameFileChange:
    """A changed file and the number of replacements applied to it."""

    path: Path
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _normalize_name(value: str | None) -> str:
    return (value or "").strip().strip("“”\"'`")


def _parse_alias_pairs(aliases: str | list[str] | tuple[str, ...] | None) -> list[tuple[str, str]]:
    """Parse alias pairs from '旧称=新称,旧称2=新称2' or repeated list values."""
    if not aliases:
        return []
    if isinstance(aliases, str):
        raw_parts = re.split(r"[,，;；\n]+", aliases)
    else:
        raw_parts = []
        for item in aliases:
            raw_parts.extend(re.split(r"[,，;；\n]+", str(item)))

    pairs: list[tuple[str, str]] = []
    for raw in raw_parts:
        item = raw.strip()
        if not item:
            continue
        if "=>" in item:
            old, new = item.split("=>", 1)
        elif "->" in item:
            old, new = item.split("->", 1)
        elif "=" in item:
            old, new = item.split("=", 1)
        elif "：" in item:
            old, new = item.split("：", 1)
        elif ":" in item:
            old, new = item.split(":", 1)
        else:
            continue
        old_name = _normalize_name(old)
        new_name = _normalize_name(new)
        if old_name and new_name:
            pairs.append((old_name, new_name))
    return pairs


def _add_mapping(
    mappings: list[RenameMapping],
    seen: set[str],
    old: str,
    new: str,
    *,
    reason: str,
    source: str,
) -> None:
    old = _normalize_name(old)
    new = _normalize_name(new)
    if not old or not new or old == new:
        return
    if len(old) < 2:
        return
    if old in _RELATIONSHIP_TERMS:
        return
    if old in seen:
        return
    seen.add(old)
    mappings.append(RenameMapping(old=old, new=new, reason=reason, source=source))


def _default_alias_mappings(old_name: str, new_name: str) -> list[RenameMapping]:
    """Build conservative deterministic mappings for common Chinese name variants."""
    mappings: list[RenameMapping] = []
    seen: set[str] = set()
    _add_mapping(
        mappings,
        seen,
        old_name,
        new_name,
        reason="完整角色名",
        source="required",
    )

    if len(old_name) >= 2 and len(new_name) >= 2:
        old_surname = old_name[0]
        new_surname = new_name[0]
        if old_surname != new_surname:
            for suffix in _TITLE_SUFFIXES:
                _add_mapping(
                    mappings,
                    seen,
                    old_surname + suffix,
                    new_surname + suffix,
                    reason="姓氏加职称/尊称",
                    source="auto",
                )

    old_given = old_name[1:] if len(old_name) >= 3 else ""
    new_given = new_name[1:] if len(new_name) >= 3 else ""
    if old_given and new_given:
        given_new = new_given
        given_reason = "去姓后的常用称呼"
        if (
            len(old_given) == 2
            and old_given[0] in {"小", "阿", "老"}
            and not new_given.startswith(old_given[0])
        ):
            given_new = old_given[0] + new_given[-1]
            given_reason = f"{old_given[0]}字昵称"
        _add_mapping(
            mappings,
            seen,
            old_given,
            given_new,
            reason=given_reason,
            source="auto",
        )

    old_last = old_given[-1:] if old_given else old_name[-1:]
    new_last = new_given[-1:] if new_given else new_name[-1:]
    if old_last and new_last and old_last != new_last:
        for prefix in ("小", "阿", "老"):
            _add_mapping(
                mappings,
                seen,
                prefix + old_last,
                prefix + new_last,
                reason=f"{prefix}字昵称",
                source="auto",
            )
        _add_mapping(
            mappings,
            seen,
            old_last + old_last,
            new_last + new_last,
            reason="叠字昵称",
            source="auto",
        )

    return mappings


def _project_text_files(root: Path) -> list[Path]:
    """Return active project text files that should participate in a rename."""
    paths = project_fs.project_paths(root)
    roots = [
        paths["chapters_dir"],
        paths["outline_dir"],
        paths["settings_dir"],
        paths["reviews_dir"],
        paths["contracts_dir"],
        paths["commits_dir"],
        paths["aznovel_dir"] / "candidates",
    ]

    files: list[Path] = []
    for directory in roots:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES:
                files.append(path)

    for path in (paths["state_file"], paths["aznovel_dir"] / project_fs.MASTER_SETTING_FILE):
        if path.exists() and path.suffix.lower() in _TEXT_SUFFIXES:
            files.append(path)

    for path in root.iterdir():
        if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES:
            files.append(path)

    return sorted(set(files), key=lambda item: str(item.relative_to(root)))


def _read_text_files(files: list[Path]) -> dict[Path, str]:
    data: dict[Path, str] = {}
    for path in files:
        try:
            data[path] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    return data


def _extract_contexts(files: dict[Path, str], root: Path, old_name: str, limit: int = 24) -> list[str]:
    contexts: list[str] = []
    pattern = re.escape(old_name)
    for path, text in files.items():
        for match in re.finditer(pattern, text):
            start = max(0, match.start() - 60)
            end = min(len(text), match.end() + 60)
            snippet = text[start:end].replace("\n", " ")
            contexts.append(f"{path.relative_to(root)}: ...{snippet}...")
            if len(contexts) >= limit:
                return contexts
    return contexts


async def _llm_alias_mappings(
    provider: LLMProvider | None,
    *,
    root: Path,
    files: dict[Path, str],
    old_name: str,
    new_name: str,
    existing_mappings: list[RenameMapping],
) -> list[RenameMapping]:
    """Ask the model to identify nickname mappings. Falls back silently on failure."""
    if provider is None:
        return []

    contexts = _extract_contexts(files, root, old_name)
    if not contexts:
        return []

    existing = "\n".join(f"- {item.old} => {item.new}" for item in existing_mappings)
    prompt = f"""你是小说项目的角色改名规划器。

任务：把角色「{old_name}」改名为「{new_name}」。

请根据上下文识别这个角色的称谓、昵称、小名、叠字称呼，并给出 exact old/new 映射。

严格规则：
1. 不要输出亲属关系、职业、身份词，例如爸爸、儿子、教授、医生、老板。
2. 不要输出一个字的映射。
3. 不要把商品名、组织名、地点名、普通名词当成昵称。
4. old 必须是文本中真实出现的连续字符串；new 必须是对应新称谓。
5. 已有映射不要重复。

已有映射：
{existing}

上下文：
{chr(10).join(contexts)}

只输出 JSON：
{{
  "mappings": [
    {{"old": "旧称谓", "new": "新称谓", "reason": "为什么这是同一角色称谓"}}
  ]
}}"""
    messages = [
        {"role": "system", "content": "你只输出可解析 JSON，不要输出解释。"},
        {"role": "user", "content": prompt},
    ]
    try:
        data = await provider.chat_json(messages, temperature=0.0, max_tokens=2048)
    except Exception:
        return []

    if not isinstance(data, dict):
        return []
    raw_mappings = data.get("mappings", [])
    if not isinstance(raw_mappings, list):
        return []

    corpus = "\n".join(files.values())
    seen = {item.old for item in existing_mappings}
    mappings: list[RenameMapping] = []
    for item in raw_mappings:
        if not isinstance(item, dict):
            continue
        old = _normalize_name(str(item.get("old", "")))
        new = _normalize_name(str(item.get("new", "")))
        if old not in corpus:
            continue
        _add_mapping(
            mappings,
            seen,
            old,
            new,
            reason=str(item.get("reason", "LLM 识别称谓")),
            source="llm",
        )
    return mappings


def _filter_observed_mappings(
    mappings: list[RenameMapping],
    corpus: str,
) -> list[RenameMapping]:
    """Keep required mappings and observed aliases; drop invented unused aliases."""
    result: list[RenameMapping] = []
    seen: set[str] = set()
    for item in sorted(mappings, key=lambda x: len(x.old), reverse=True):
        if item.old in seen:
            continue
        if item.source != "required" and item.old not in corpus:
            continue
        seen.add(item.old)
        result.append(item)
    return result


def _apply_mappings(text: str, mappings: list[RenameMapping]) -> tuple[str, dict[str, int]]:
    result = text
    counts: dict[str, int] = {}
    for item in mappings:
        count = result.count(item.old)
        if count <= 0:
            continue
        result = result.replace(item.old, item.new)
        counts[item.old] = count
    return result, counts


def _mirror_path(base: Path, root: Path, path: Path) -> Path:
    return base / path.relative_to(root)


def _write_report(
    report_path: Path,
    *,
    old_name: str,
    new_name: str,
    mappings: list[RenameMapping],
    changes: list[RenameFileChange],
    warnings: list[str],
    validation_errors: list[str],
    dry_run: bool,
) -> None:
    lines = ["# 角色改名报告\n"]
    lines.append(f"- 模式: {'演练' if dry_run else '正式改名'}")
    lines.append(f"- 旧名: {old_name}")
    lines.append(f"- 新名: {new_name}")
    lines.append(f"- 修改文件: {len(changes)}")
    lines.append(f"- 替换次数: {sum(item.total for item in changes)}")

    lines.append("\n## 称谓映射\n")
    for item in mappings:
        lines.append(f"- `{item.old}` -> `{item.new}` ({item.source}; {item.reason})")

    lines.append("\n## 修改文件\n")
    if changes:
        for change in changes:
            detail = ", ".join(f"{old} x{count}" for old, count in change.counts.items())
            lines.append(f"- `{change.path}`: {detail}")
    else:
        lines.append("无")

    lines.append("\n## 警告\n")
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("无")

    lines.append("\n## 校验结果\n")
    if validation_errors:
        lines.extend(f"- {item}" for item in validation_errors)
    else:
        lines.append("全部映射通过残留校验。")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def rename_character(
    provider: LLMProvider | None,
    root: Path,
    *,
    old_name: str,
    new_name: str,
    aliases: str | list[str] | tuple[str, ...] | None = None,
    dry_run: bool = False,
    on_step=None,
) -> bool:
    """Rename a character and related nicknames with auditable exact mappings."""
    def _step(message: str) -> None:
        info(message)
        if on_step:
            on_step(message)

    old_name = _normalize_name(old_name)
    new_name = _normalize_name(new_name)
    if not old_name or not new_name:
        error("角色改名需要同时提供旧名和新名。")
        return False
    if old_name == new_name:
        warn("旧名和新名相同，无需改名。")
        return True

    StateStore(root).load()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = project_fs.project_paths(root)["aznovel_dir"] / "renames" / timestamp
    report_path = session_dir / "report.md"
    before_dir = session_dir / "before"
    after_dir = session_dir / "after"

    _step("角色改名：扫描项目文本...")
    file_paths = _project_text_files(root)
    originals = _read_text_files(file_paths)
    corpus = "\n".join(originals.values())
    if old_name not in corpus:
        error(f"未在项目文本中找到旧名：{old_name}")
        return False

    warnings: list[str] = []
    if new_name in corpus:
        warnings.append(f"目标名 `{new_name}` 在改名前已经出现在项目文本中，请确认不是另一个角色。")

    mappings = _default_alias_mappings(old_name, new_name)
    explicit_seen = {item.old for item in mappings}
    for old_alias, new_alias in _parse_alias_pairs(aliases):
        _add_mapping(
            mappings,
            explicit_seen,
            old_alias,
            new_alias,
            reason="用户显式提供的称谓映射",
            source="explicit",
        )

    _step("角色改名：识别小名、昵称和关联称谓...")
    llm_mappings = await _llm_alias_mappings(
        provider,
        root=root,
        files=originals,
        old_name=old_name,
        new_name=new_name,
        existing_mappings=mappings,
    )
    mappings.extend(llm_mappings)
    mappings = _filter_observed_mappings(mappings, corpus)

    if not mappings:
        error("没有可应用的改名映射。")
        return False

    _step(f"角色改名：应用 {len(mappings)} 个受控称谓映射...")
    candidates: dict[Path, str] = {}
    changes: list[RenameFileChange] = []
    for path, text in originals.items():
        updated, counts = _apply_mappings(text, mappings)
        candidates[path] = updated
        if counts:
            changes.append(
                RenameFileChange(path=path.relative_to(root), counts=counts)
            )

    validation_errors: list[str] = []
    for item in mappings:
        if item.old in item.new:
            continue
        residuals = []
        for path, text in candidates.items():
            if item.old in text:
                residuals.append(str(path.relative_to(root)))
                if len(residuals) >= 5:
                    break
        if residuals:
            validation_errors.append(
                f"`{item.old}` 仍残留于 {', '.join(residuals)}"
            )

    before_dir.mkdir(parents=True, exist_ok=True)
    after_dir.mkdir(parents=True, exist_ok=True)
    for change in changes:
        absolute = root / change.path
        _mirror_path(before_dir, root, absolute).parent.mkdir(parents=True, exist_ok=True)
        _mirror_path(after_dir, root, absolute).parent.mkdir(parents=True, exist_ok=True)
        _mirror_path(before_dir, root, absolute).write_text(originals[absolute], encoding="utf-8")
        _mirror_path(after_dir, root, absolute).write_text(candidates[absolute], encoding="utf-8")

    _write_report(
        report_path,
        old_name=old_name,
        new_name=new_name,
        mappings=mappings,
        changes=changes,
        warnings=warnings,
        validation_errors=validation_errors,
        dry_run=dry_run,
    )

    latest_report = project_fs.project_paths(root)["aznovel_dir"] / "renames" / "latest_report.md"
    latest_report.parent.mkdir(parents=True, exist_ok=True)
    latest_report.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

    if validation_errors:
        warn(f"角色改名未通过残留校验，正式文件未覆盖。报告: {report_path}")
        for item in validation_errors[:8]:
            warn(f"  - {item}")
        return False

    if dry_run:
        success(f"角色改名演练完成：将修改 {len(changes)} 个文件。报告: {report_path}")
        return True

    _step("角色改名：覆盖通过校验的项目文件...")
    for change in changes:
        absolute = root / change.path
        absolute.write_text(candidates[absolute], encoding="utf-8")

    success(f"角色改名完成：{old_name} -> {new_name}，修改 {len(changes)} 个文件。")
    info(f"改名报告: {report_path}")
    return True
