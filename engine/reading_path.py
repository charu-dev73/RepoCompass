"""Generate a guided reading path through a Python repository."""

from dataclasses import dataclass
from pathlib import Path

from engine.entrypoints import _is_supporting_path, _is_test_path
from engine.graph import DependencyGraph
from engine.parse import FileInfo


GENERIC_DIRECTORY_NAMES = {
    "compat",
    "compatibility",
    "external",
    "externals",
    "fixtures",
    "helper",
    "helpers",
    "internal",
    "testing",
    "util",
    "utils",
    "vendor",
    "vendored",
}

GENERIC_MODULE_NAMES = {
    "__main__",
    "__version__",
    "certs",
    "compat",
    "config",
    "conftest",
    "constants",
    "exceptions",
    "fixtures",
    "help",
    "helper",
    "helpers",
    "noxfile",
    "packages",
    "settings",
    "setup",
    "status_codes",
    "testing",
    "types",
    "util",
    "utils",
    "version",
}

API_SEED_LIMIT = 2
CORE_SEED_LIMIT = 3
SECONDARY_SEED_LIMIT = 2
MAX_SEED_COUNT = 6
PUBLIC_API_BONUS = 30
GENERIC_DIRECTORY_PENALTY = 250
GENERIC_MODULE_PENALTY = 80
PRIVATE_MODULE_PENALTY = 30
DISCONNECTED_DEPTH = 999


@dataclass(frozen=True)
class ReadingStep:
    path: Path
    reason: str
    order: int


def _steps(candidates: list[tuple[Path, int, str]]) -> list[ReadingStep]:
    return [
        ReadingStep(path=path, reason=reason, order=index + 1)
        for index, (path, _, reason) in enumerate(candidates)
    ]


def _generic_penalty(path: Path) -> int:
    path = Path(path)
    penalty = sum(
        GENERIC_DIRECTORY_PENALTY
        for part in path.parts[:-1]
        if part.lower() in GENERIC_DIRECTORY_NAMES
    )

    if path.name != "__init__.py":
        if path.stem.lower() in GENERIC_MODULE_NAMES:
            penalty += GENERIC_MODULE_PENALTY

    return penalty


def _api_base_directories(api_paths: list[Path]) -> set[Path]:
    return {Path(path).parent for path in api_paths}


def _relative_parts(path: Path, base_directories: set[Path]) -> tuple[str, ...]:
    path = Path(path)
    matches = [
        base
        for base in base_directories
        if base == path.parent or base in path.parents
    ]

    if not matches:
        return path.parts

    base = max(matches, key=lambda candidate: len(candidate.parts))
    return path.relative_to(base).parts


def _private_penalty(path: Path, base_directories: set[Path]) -> int:
    path = Path(path)
    relative = _relative_parts(path, base_directories)

    if any(part.startswith("_") for part in relative[:-1]):
        return PRIVATE_MODULE_PENALTY

    if path.name != "__init__.py" and path.stem.startswith("_"):
        return PRIVATE_MODULE_PENALTY

    return 0


def _module_penalty(path: Path, base_directories: set[Path]) -> int:
    return (
        _generic_penalty(path)
        + _private_penalty(path, base_directories)
    )


def _valid_paths(
    graph: DependencyGraph,
    file_infos: list[FileInfo] | None,
) -> set[Path]:
    nodes = set(graph.nodes())

    if file_infos is None:
        return nodes

    invalid = {
        Path(info.path)
        for info in file_infos
        if info.parse_error is not None
    }

    return nodes - invalid


def _production_in_degree(
    graph: DependencyGraph,
    path: Path,
    valid_paths: set[Path],
) -> int:
    return sum(
        1
        for importer in graph.importers_of.get(path, set())
        if importer in valid_paths and not _is_supporting_path(importer)
    )


def _production_out_degree(
    graph: DependencyGraph,
    path: Path,
    valid_paths: set[Path],
) -> int:
    return sum(
        1
        for dependency in graph.imports_of.get(path, set())
        if dependency in valid_paths and not _is_supporting_path(dependency)
    )


def _production_score(
    graph: DependencyGraph,
    path: Path,
    valid_paths: set[Path],
) -> tuple[int, int, int]:
    incoming = _production_in_degree(graph, path, valid_paths)
    outgoing = _production_out_degree(graph, path, valid_paths)
    return incoming * 2 + outgoing, incoming, outgoing


def _diverse_paths(
    scored: list[tuple[int, int, int, str, Path]],
    limit: int,
) -> list[Path]:
    ordered = sorted(
        scored,
        key=lambda item: (-item[0], -item[1], -item[2], item[3]),
    )
    selected: list[Path] = []
    seen: set[Path] = set()
    directories: set[Path] = set()

    for item in ordered:
        path = item[-1]
        directory = path.parent

        if directory in directories:
            continue

        selected.append(path)
        seen.add(path)
        directories.add(directory)

        if len(selected) == limit:
            return selected

    for item in ordered:
        path = item[-1]

        if path in seen:
            continue

        selected.append(path)
        seen.add(path)

        if len(selected) == limit:
            break

    return selected


def _namespace_api_paths(
    graph: DependencyGraph,
    valid_paths: set[Path],
) -> list[Path]:
    candidates = [
        path
        for path in valid_paths
        if path.name != "__init__.py"
        and not _is_supporting_path(path)
    ]

    if not candidates:
        return []

    non_generic = [
        path
        for path in candidates
        if _generic_penalty(path) == 0
    ]
    pool = non_generic or candidates
    minimum_depth = min(len(path.parts) for path in pool)
    scored = []

    for path in pool:
        if len(path.parts) != minimum_depth:
            continue

        score, incoming, outgoing = _production_score(
            graph,
            path,
            valid_paths,
        )
        scored.append((score, incoming, outgoing, str(path), path))

    return _diverse_paths(scored, API_SEED_LIMIT)


def _public_api_path(
    graph: DependencyGraph,
    valid_paths: set[Path],
) -> list[Path]:
    candidates = [
        path
        for path in valid_paths
        if path.name == "__init__.py"
        and not _is_supporting_path(path)
    ]

    if not candidates:
        return _namespace_api_paths(graph, valid_paths)

    minimum_depth = min(len(path.parts) for path in candidates)
    scored = []

    for path in candidates:
        if len(path.parts) != minimum_depth:
            continue

        score, incoming, outgoing = _production_score(
            graph,
            path,
            valid_paths,
        )
        scored.append((score, incoming, outgoing, str(path), path))

    scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))

    return [item[-1] for item in scored[:API_SEED_LIMIT]]


def _core_seeds(
    graph: DependencyGraph,
    valid_paths: set[Path],
    api_paths: list[Path],
) -> list[Path]:
    api_path_set = set(api_paths)
    public_api_dependencies = {
        dependency
        for path in api_paths
        for dependency in graph.imports_of.get(path, set())
    }
    base_directories = _api_base_directories(api_paths)
    scored = []

    for path in valid_paths:
        if path in api_path_set or _is_supporting_path(path):
            continue

        score, incoming, outgoing = _production_score(
            graph,
            path,
            valid_paths,
        )

        if path in public_api_dependencies:
            score += PUBLIC_API_BONUS

        score -= _module_penalty(path, base_directories)

        if score <= 0:
            continue

        scored.append((score, incoming, outgoing, str(path), path))

    return _diverse_paths(scored, CORE_SEED_LIMIT)


def _secondary_seeds(
    secondary_entrypoints: list[Path] | None,
    valid_paths: set[Path],
) -> list[Path]:
    selected: list[Path] = []

    for path in map(Path, secondary_entrypoints or []):
        if path not in valid_paths or _is_test_path(path):
            continue

        if path in selected:
            continue

        selected.append(path)

        if len(selected) == SECONDARY_SEED_LIMIT:
            break

    return selected


def _bound_seeds(
    api_paths: list[Path],
    core_paths: list[Path],
    secondary_paths: list[Path],
    max_files: int,
) -> tuple[list[Path], list[Path], list[Path]]:
    seed_budget = 1 if max_files <= 1 else min(
        MAX_SEED_COUNT,
        max_files - 1,
    )
    api_count = min(len(api_paths), API_SEED_LIMIT, seed_budget)
    remaining = seed_budget - api_count
    core_count = min(len(core_paths), CORE_SEED_LIMIT, remaining)
    remaining -= core_count
    secondary_count = min(
        len(secondary_paths),
        SECONDARY_SEED_LIMIT,
        remaining,
    )

    return (
        secondary_paths[:secondary_count],
        api_paths[:api_count],
        core_paths[:core_count],
    )


def _dependency_key(
    path: Path,
    prefer_production: bool,
    base_directories: set[Path],
) -> tuple[int, int, int, str]:
    if not prefer_production:
        return (0, 0, 0, str(path))

    return (
        1 if _is_supporting_path(path) else 0,
        _generic_penalty(path),
        _private_penalty(path, base_directories),
        str(path),
    )


def _walk_dependencies(
    graph: DependencyGraph,
    seeds: list[Path],
    visited: set[Path],
    candidates: list[tuple[Path, int, str]],
    *,
    prefer_production: bool,
    include_tests: bool,
    allowed_paths: set[Path] | None,
    base_directories: set[Path],
) -> None:
    nodes = set(graph.nodes())
    queue = [(path, 0) for path in seeds]
    index = 0

    while index < len(queue):
        current, depth = queue[index]
        index += 1

        dependencies = sorted(
            graph.imports_of.get(current, set()),
            key=lambda path: _dependency_key(
                path,
                prefer_production,
                base_directories,
            ),
        )

        for dependency in dependencies:
            if dependency not in nodes or dependency in visited:
                continue

            if allowed_paths is not None and dependency not in allowed_paths:
                continue

            if not include_tests and _is_test_path(dependency):
                continue

            visited.add(dependency)
            queue.append((dependency, depth + 1))

            reason = (
                f"Imported by {current}"
                if depth == 0
                else f"Dependency reached through {current}"
            )
            candidates.append((dependency, depth + 1, reason))


def _fallback_order(
    graph: DependencyGraph,
    nodes: set[Path],
    valid_paths: set[Path],
    excluded: set[Path],
    *,
    include_tests: bool,
    base_directories: set[Path],
) -> list[Path]:
    candidates = [
        path
        for path in nodes - excluded
        if path in valid_paths
        and (include_tests or not _is_test_path(path))
    ]

    return sorted(
        candidates,
        key=lambda path: (
            1 if _is_supporting_path(path) else 0,
            1 if _is_test_path(path) else 0,
            _generic_penalty(path),
            _private_penalty(path, base_directories),
            -_production_in_degree(graph, path, valid_paths),
            -graph.in_degree(path),
            str(path),
        ),
    )


def _representative_test(
    graph: DependencyGraph,
    valid_paths: set[Path],
    core_targets: set[Path],
    all_targets: set[Path],
) -> Path | None:
    if not all_targets:
        return None

    scored = []

    for path in valid_paths:
        if not _is_test_path(path) or path.name == "__init__.py":
            continue

        name = path.name.lower()

        if not (name.startswith("test_") or name.endswith("_test.py")):
            continue

        imports = graph.imports_of.get(path, set())
        core_overlap = len(imports & core_targets)
        total_overlap = len(imports & all_targets)

        if total_overlap == 0:
            continue

        scored.append(
            (
                core_overlap,
                total_overlap,
                len(imports & valid_paths),
                str(path),
                path,
            )
        )

    if not scored:
        return None

    scored.sort(
        key=lambda item: (
            -item[0],
            -item[1],
            -item[2],
            item[3],
        )
    )

    return scored[0][-1]


def _generate_primary_path(
    graph: DependencyGraph,
    entrypoints: list[Path],
    max_files: int,
) -> list[ReadingStep]:
    nodes = set(graph.nodes())
    visited: set[Path] = set()
    candidates: list[tuple[Path, int, str]] = []
    seeds: list[Path] = []

    for path in map(Path, entrypoints):
        if path in nodes and path not in visited:
            visited.add(path)
            seeds.append(path)
            candidates.append((path, 0, "Detected application entry point"))

    _walk_dependencies(
        graph,
        seeds,
        visited,
        candidates,
        prefer_production=False,
        include_tests=True,
        allowed_paths=None,
        base_directories=set(),
    )

    for path in sorted(
        nodes - visited,
        key=lambda path: (-graph.in_degree(path), str(path)),
    ):
        candidates.append(
            (
                path,
                DISCONNECTED_DEPTH,
                "Additional repository file not reached from an entry point",
            )
        )

    return _steps(candidates[:max_files])


def _generate_library_path(
    graph: DependencyGraph,
    secondary_entrypoints: list[Path] | None,
    file_infos: list[FileInfo] | None,
    max_files: int,
) -> list[ReadingStep]:
    nodes = set(graph.nodes())
    valid_paths = _valid_paths(graph, file_infos)
    api_paths = _public_api_path(graph, valid_paths)
    core_paths = _core_seeds(graph, valid_paths, api_paths)
    secondary_paths = _secondary_seeds(
        secondary_entrypoints,
        valid_paths,
    )
    secondary_seeds, api_seeds, core_seeds = _bound_seeds(
        api_paths,
        core_paths,
        secondary_paths,
        max_files,
    )
    base_directories = _api_base_directories(api_paths)

    seeds = secondary_seeds + api_seeds + core_seeds

    if not seeds:
        ordered = _fallback_order(
            graph,
            nodes,
            valid_paths,
            set(),
            include_tests=True,
            base_directories=base_directories,
        )
        return _steps(
            [
                (
                    path,
                    DISCONNECTED_DEPTH,
                    "Additional repository file not reached from an entry point",
                )
                for path in ordered[:max_files]
            ]
        )

    reasons: dict[Path, str] = {}

    for path in secondary_seeds:
        reasons[path] = "Example or supporting entry point"

    for path in api_seeds:
        reasons[path] = "Package public API"

    for path in core_seeds:
        reasons[path] = "Core implementation module"

    visited = set(seeds)
    candidates = [
        (path, 0, reasons[path])
        for path in seeds
    ]

    _walk_dependencies(
        graph,
        seeds,
        visited,
        candidates,
        prefer_production=True,
        include_tests=False,
        allowed_paths=valid_paths,
        base_directories=base_directories,
    )

    seed_candidates = candidates[:len(seeds)]
    dependency_candidates = candidates[len(seeds):]
    dependency_candidates.sort(
        key=lambda item: (
            1 if _is_supporting_path(item[0]) else 0,
            _generic_penalty(item[0]),
            _private_penalty(item[0], base_directories),
            item[1],
            -_production_in_degree(graph, item[0], valid_paths),
            str(item[0]),
        )
    )
    candidates = seed_candidates + dependency_candidates

    representative_test = _representative_test(
        graph,
        valid_paths,
        set(core_seeds),
        set(seeds),
    )
    selected = candidates[:max_files]

    if len(selected) < max_files:
        selected_paths = {path for path, _, _ in selected}
        ordered = _fallback_order(
            graph,
            nodes,
            valid_paths,
            selected_paths,
            include_tests=False,
            base_directories=base_directories,
        )

        for path in ordered:
            if len(selected) >= max_files:
                break

            selected.append(
                (
                    path,
                    DISCONNECTED_DEPTH,
                    "Additional repository file not reached from an entry point",
                )
            )

    if representative_test is not None and len(selected) < max_files:
        selected.append(
            (
                representative_test,
                1,
                "Test demonstrating core behavior",
            )
        )

    return _steps(selected[:max_files])


def generate_reading_path(
    graph: DependencyGraph,
    entrypoints: list[Path],
    max_files: int = 8,
    *,
    secondary_entrypoints: list[Path] | None = None,
    file_infos: list[FileInfo] | None = None,
) -> list[ReadingStep]:
    """Return a deterministic reading path through the repository."""
    if max_files <= 0 or not graph.nodes():
        return []

    raw_entrypoints = list(entrypoints)

    if raw_entrypoints:
        return _generate_primary_path(
            graph,
            raw_entrypoints,
            max_files,
        )

    return _generate_library_path(
        graph,
        secondary_entrypoints,
        file_infos,
        max_files,
    )
