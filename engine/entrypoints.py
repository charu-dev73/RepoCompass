
"""Detect likely Python application entry points."""

from dataclasses import dataclass, field
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

SUPPORTING_DIRECTORY_NAMES = {
    "test",
    "tests",
    "testing",
    "fixtures",
    "example",
    "examples",
    "sample",
    "samples",
    "demo",
    "demos",
    "docs",
    "doc",
    "documentation",
    "benchmark",
    "benchmarks",
    "bench",
    "tutorial",
    "tutorials",
}

# A main guard alone is weaker evidence than a conventional entry-point name.
# It usually marks a script that can be run directly, but library modules also
# use it to support direct execution.
STANDALONE_MAIN_GUARD_SCORE = 60


@dataclass
class EntrypointGroups:
    primary: list[Path] = field(default_factory=list)
    secondary: list[Path] = field(default_factory=list)


def _is_test_path(path: Path) -> bool:
    """Return True when a path looks like part of a test suite."""
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()

    return (
        "tests" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _is_supporting_path(path: Path) -> bool:
    """Return True for runnable files in test or example-style directories."""
    if _is_test_path(path):
        return True

    return any(
        part.lower() in SUPPORTING_DIRECTORY_NAMES
        for part in path.parts[:-1]
    )


def _sorted_paths(scores: dict[Path, int]) -> list[Path]:
    return sorted(scores, key=lambda path: (-scores[path], str(path)))


def _imported_by_source(
    path: Path,
    graph: DependencyGraph | None,
) -> bool:
    """True when a non-test module imports this file."""
    if graph is None:
        return False

    return any(
        not _is_test_path(Path(importer))
        for importer in graph.importers_of.get(path, set())
    )


def _package_directories(files: list[FileInfo]) -> set[Path]:
    """Return directories that are Python packages."""
    return {
        Path(info.path).parent
        for info in files
        if Path(info.path).name == "__init__.py"
    }


def _score_entrypoint(
    info: FileInfo,
    path: Path,
    graph: DependencyGraph | None,
    package_dirs: set[Path],
) -> int:
    score = ENTRYPOINT_NAMES.get(path.name.lower(), 0)

    if not info.has_main_guard:
        return score

    if score > 0:
        # Conventional entry-point names keep their existing priority.
        return score

    # A non-conventional module inside a package is usually a library utility
    # that supports direct execution, not the application's entry point.
    if path.parent in package_dirs:
        return 0

    # An imported module with a main guard is also likely a utility.
    if _imported_by_source(path, graph):
        return 0

    return STANDALONE_MAIN_GUARD_SCORE


def detect_entrypoint_groups(
    files: list[FileInfo],
    graph: DependencyGraph | None = None,
) -> EntrypointGroups:
    """Return primary and secondary entry-point files in priority order."""
    primary_scores: dict[Path, int] = {}
    secondary_scores: dict[Path, int] = {}
    package_dirs = _package_directories(files)

    for info in files:
        path = Path(info.path)

        # Files with syntax or read errors cannot provide reliable evidence.
        if info.parse_error is not None:
            continue

        score = _score_entrypoint(
            info,
            path,
            graph,
            package_dirs,
        )

        if score <= 0:
            continue

        if _is_supporting_path(path):
            secondary_scores[path] = score
        else:
            primary_scores[path] = score

    return EntrypointGroups(
        primary=_sorted_paths(primary_scores),
        secondary=_sorted_paths(secondary_scores),
    )


def detect_entrypoints(
    files: list[FileInfo],
    graph: DependencyGraph | None = None,
) -> list[Path]:
    """Return primary entry-point files in priority order."""
    return detect_entrypoint_groups(files, graph).primary
