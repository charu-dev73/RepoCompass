
"""Generate a guided reading path through a Python repository."""

from dataclasses import dataclass
from pathlib import Path

from engine.graph import DependencyGraph


@dataclass(frozen=True)
class ReadingStep:
    path: Path
    reason: str
    order: int


def generate_reading_path(
    graph: DependencyGraph,
    entrypoints: list[Path],
    max_files: int = 8,
) -> list[ReadingStep]:
    """Return a deterministic reading path from entry points through imports."""
    if max_files <= 0 or not graph.nodes():
        return []

    nodes = set(graph.nodes())
    queue: list[tuple[Path, int]] = []
    visited: set[Path] = set()
    candidates: list[tuple[Path, int, str]] = []

    # Prefer detected entry points that actually exist in the graph.
    for path in sorted(set(map(Path, entrypoints)), key=str):
        if path in nodes and path not in visited:
            visited.add(path)
            queue.append((path, 0))
            candidates.append((path, 0, "Detected application entry point"))

    # Breadth-first traversal follows importer -> dependency edges.
    index = 0
    while index < len(queue):
        current, depth = queue[index]
        index += 1

        dependencies = sorted(
            graph.imports_of.get(current, set()),
            key=str,
        )

        for dependency in dependencies:
            if dependency not in nodes or dependency in visited:
                continue

            visited.add(dependency)
            queue.append((dependency, depth + 1))

            reason = (
                f"Imported by {current}"
                if depth == 0
                else f"Dependency reached through {current}"
            )
            candidates.append((dependency, depth + 1, reason))

    # Include disconnected files when the entry points cannot reach them.
    # Files with more incoming dependencies are more central.
    remaining = sorted(
        nodes - visited,
        key=lambda path: (-graph.in_degree(path), str(path)),
    )

    for path in remaining:
        candidates.append(
            (path, 999, "Additional repository file not reached from an entry point")
        )

    return [
        ReadingStep(path=path, reason=reason, order=index + 1)
        for index, (path, _, reason) in enumerate(candidates[:max_files])
    ]
