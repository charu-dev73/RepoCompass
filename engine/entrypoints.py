
"""Detect likely Python application entry points."""

from pathlib import Path

from engine.graph import DependencyGraph
from engine.parse import FileInfo


ENTRYPOINT_NAMES = {
    "main.py": 100,
    "__main__.py": 100,
    "cli.py": 90,
    "app.py": 80,
    "run.py": 80,
    "manage.py": 80,
}


def detect_entrypoints(
    files: list[FileInfo],
    graph: DependencyGraph | None = None,
) -> list[Path]:
    """Return likely entry-point files in priority order."""
    scores: dict[Path, int] = {}

    for info in files:
        path = Path(info.path)

        # Files with syntax or read errors cannot provide reliable evidence.
        if info.parse_error is not None:
            continue

        score = ENTRYPOINT_NAMES.get(path.name.lower(), 0)

        if info.has_main_guard:
            score = max(score, 100)

        if score > 0:
            scores[path] = score

    # Higher scores first, then alphabetical order for deterministic results.
    return sorted(scores, key=lambda path: (-scores[path], str(path)))
