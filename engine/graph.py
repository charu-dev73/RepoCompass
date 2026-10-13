
"""Build a dependency graph from parsed Python files."""

from dataclasses import dataclass, field
from pathlib import Path

from engine.parse import FileInfo
from engine.resolve import (
    build_module_map,
    resolve_absolute_import,
    resolve_relative_import,
)


@dataclass
class DependencyGraph:
    """Directed graph where A -> B means A imports B."""

    imports_of: dict[Path, set[Path]] = field(default_factory=dict)
    importers_of: dict[Path, set[Path]] = field(default_factory=dict)

    def nodes(self) -> list[Path]:
        """Return all graph nodes in deterministic order."""
        return sorted(self.imports_of, key=str)

    def edges(self) -> list[tuple[Path, Path]]:
        """Return all edges in deterministic order."""
        return sorted(
            (
                (source, target)
                for source, dependencies in self.imports_of.items()
                for target in dependencies
            ),
            key=lambda edge: (str(edge[0]), str(edge[1])),
        )

    def in_degree(self, path: Path) -> int:
        """Return the number of files importing this file."""
        return len(self.importers_of.get(Path(path), set()))

    def out_degree(self, path: Path) -> int:
        """Return the number of files imported by this file."""
        return len(self.imports_of.get(Path(path), set()))


def build_dependency_graph(
    files: list[FileInfo],
    module_map: dict[str, Path] | None = None,
) -> DependencyGraph:
    """Build a graph using resolved imports from parsed Python files."""
    paths = [Path(info.path) for info in files]

    if module_map is None:
        module_map = build_module_map(paths)

    graph = DependencyGraph()

    # Every discovered file is a node, including files with parse errors.
    for path in paths:
        graph.imports_of.setdefault(path, set())
        graph.importers_of.setdefault(path, set())

    known_paths = set(paths)

    for info in files:
        source = Path(info.path)

        # A file that could not be parsed has no known outgoing imports.
        if info.parse_error is not None:
            continue

        for record in info.imports:
            if record.level > 0:
                resolved = resolve_relative_import(
                    record,
                    source,
                    module_map,
                )
            else:
                resolved = resolve_absolute_import(record, module_map)

            for dependency in resolved:
                dependency = Path(dependency)

                # Never create edges to files outside this graph.
                if dependency not in known_paths:
                    continue

                # Ignore self-import edges.
                if dependency == source:
                    continue

                graph.imports_of[source].add(dependency)
                graph.importers_of[dependency].add(source)

    return graph
