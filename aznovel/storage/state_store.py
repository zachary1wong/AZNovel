"""State persistence for project state.json."""

from __future__ import annotations

from pathlib import Path

from aznovel.models.project import ProjectState
from aznovel.storage import project_fs


class StateStore:
    """Read/write project state."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._path = project_fs.project_paths(root)["state_file"]

    def load(self) -> ProjectState:
        """Load state from disk, return default if missing."""
        data = project_fs.load_json(self._path)
        if not data:
            return ProjectState()
        return ProjectState.model_validate(data)

    def save(self, state: ProjectState) -> None:
        """Save state to disk."""
        project_fs.save_json(self._path, state.model_dump())

    def update(self, fn) -> ProjectState:
        """Load state, apply fn(state), save, and return updated state."""
        state = self.load()
        fn(state)
        self.save(state)
        return state
