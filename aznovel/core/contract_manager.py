"""Contract manager - reads and writes JSON contracts."""

from __future__ import annotations

from pathlib import Path

from aznovel.models.contract import ChapterBrief, MasterSetting, ReviewContract
from aznovel.models.project import ProjectState
from aznovel.storage import project_fs


class ContractManager:
    """Manages the contract layer (.aznovel/contracts/)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._paths = project_fs.project_paths(root)

    # --- Master Setting ---

    def load_master_setting(self) -> MasterSetting:
        path = self._paths["contracts_dir"] / project_fs.MASTER_SETTING_FILE
        data = project_fs.load_json(path)
        if not data:
            return MasterSetting()
        return MasterSetting.model_validate(data)

    def save_master_setting(self, setting: MasterSetting) -> None:
        path = self._paths["contracts_dir"] / project_fs.MASTER_SETTING_FILE
        project_fs.save_json(path, setting.model_dump())

    # --- Chapter Brief ---

    def load_chapter_brief(self, chapter: int) -> ChapterBrief | None:
        path = self._paths["contracts_dir"] / f"chapter_{chapter:03d}.json"
        data = project_fs.load_json(path)
        if not data:
            return None
        return ChapterBrief.model_validate(data)

    def save_chapter_brief(self, brief: ChapterBrief) -> None:
        path = self._paths["contracts_dir"] / f"chapter_{brief.chapter_number:03d}.json"
        project_fs.save_json(path, brief.model_dump())

    # --- Review Contract ---

    def load_review_contract(self, chapter: int) -> ReviewContract | None:
        path = self._paths["contracts_dir"] / f"chapter_{chapter:03d}.review.json"
        data = project_fs.load_json(path)
        if not data:
            return None
        return ReviewContract.model_validate(data)

    def save_review_contract(self, contract: ReviewContract) -> None:
        path = self._paths["contracts_dir"] / f"chapter_{contract.chapter_number:03d}.review.json"
        project_fs.save_json(path, contract.model_dump())

    # --- Generate from state ---

    def generate_master_setting(self, state: ProjectState, genre_template: dict) -> MasterSetting:
        """Generate MasterSetting from project state + genre template."""
        return MasterSetting(
            genre=state.project_info.genre,
            sub_genres=genre_template.get("sub_genres", []),
            core_tone=genre_template.get("core_tone", ""),
            pacing_strategy=genre_template.get("pacing_strategy", ""),
            satisfaction_points=genre_template.get("satisfaction_points", []),
            anti_patterns=genre_template.get("anti_patterns", []),
            world_rules=genre_template.get("world_building", {}).get("rules", []) if isinstance(genre_template.get("world_building"), dict) else [],
            golden_finger=genre_template.get("golden_finger", ""),
            protagonist_archetype=genre_template.get("protagonist_archetype", ""),
        )

    def generate_chapter_brief(
        self,
        chapter: int,
        state: ProjectState,
        master: MasterSetting,
        outline: dict | None = None,
    ) -> ChapterBrief:
        """Generate ChapterBrief from state + master setting + outline."""
        outline = outline or {}
        summary = outline.get("summary", "")
        # 从 summary 中提取关键内容作为 must_cover
        must_cover = []
        if summary:
            must_cover.append(summary)

        return ChapterBrief(
            chapter_number=chapter,
            title=outline.get("title", f"第{chapter}章"),
            summary=summary,
            goal=outline.get("goal", ""),
            resistance=outline.get("resistance", ""),
            cost=outline.get("cost", ""),
            key_nodes=outline.get("key_nodes", []),
            character_states={
                state.protagonist.name: state.protagonist.mood or "正常",
            },
            time_anchor=outline.get("time_anchor", ""),
            ending_target=outline.get("ending_feeling", ""),
            forbidden_zones=outline.get("forbidden_zones", master.anti_patterns[:3]),
            must_cover=must_cover,
            anti_patterns=master.anti_patterns,
        )

    def generate_review_contract(
        self, chapter: int, state: ProjectState, master: MasterSetting,
        chapter_brief: ChapterBrief | None = None,
    ) -> ReviewContract:
        """Generate ReviewContract for a chapter."""
        protagonist_facts = []
        if state.protagonist.name:
            fact = f"主角是{state.protagonist.name}"
            if state.protagonist.cultivation:
                fact += f"，身份/状态：{state.protagonist.cultivation}"
            if state.protagonist.current_goal:
                fact += f"，当前目标：{state.protagonist.current_goal}"
            protagonist_facts.append(fact)

        return ReviewContract(
            chapter_number=chapter,
            known_entities=_unique_nonempty(
                [state.protagonist.name] + [e.name for e in state.entities]
            ),
            established_rules=master.world_rules + protagonist_facts,
            blocking_keywords=["[待填]", "[TODO]", "placeholder"],
            must_cover=chapter_brief.must_cover if chapter_brief else [],
            outline_summary=chapter_brief.summary if chapter_brief else "",
        )


def _unique_nonempty(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = item.strip() if item else ""
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
