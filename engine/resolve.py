
from pathlib import Path

from engine.parse import ImportRecord


def build_module_map(
    python_files: list[Path],
    source_roots: list[Path] | None = None,
) -> dict[str, Path]:
    """Map Python module names to paths relative to the repository root."""
    if source_roots is None:
        source_roots = [Path("src"), Path(".")]

    module_map: dict[str, Path] = {}

    for file_path in python_files:
        path = Path(file_path)

        for source_root in source_roots:
            try:
                relative = path.relative_to(source_root)
            except ValueError:
                continue

            if relative.suffix != ".py":
                break

            parts = list(relative.with_suffix("").parts)

            if parts[-1] == "__init__":
                parts.pop()

            if not parts:
                break

            module_name = ".".join(parts)
            module_map.setdefault(module_name, path)
            break

    return module_map


def _longest_prefix_match(
    dotted_name: str,
    module_map: dict[str, Path],
) -> Path | None:
    """Return the file for the longest dotted prefix found in the map."""
    parts = dotted_name.split(".")

    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])

        if candidate in module_map:
            return module_map[candidate]

    return None


def resolve_absolute_import(
    record: ImportRecord,
    module_map: dict[str, Path],
) -> list[Path]:
    """Resolve an absolute import to repository files, if possible."""
    if record.level > 0 or record.module is None:
        return []

    base_path = _longest_prefix_match(record.module, module_map)

    # Plain import, such as: import package.module
    if not record.names:
        return [base_path] if base_path is not None else []

    targets: list[Path] = []

    # From-import, such as: from package import module
    for name in record.names:
        submodule = f"{record.module}.{name}"

        if name != "*" and submodule in module_map:
            targets.append(module_map[submodule])
        elif base_path is not None:
            targets.append(base_path)

    return list(dict.fromkeys(targets))


def resolve_relative_import(
    record: ImportRecord,
    importer_path: Path,
    module_map: dict[str, Path],
) -> list[Path]:
    """Resolve a relative import to repository files.

    importer_path must be relative to the repository root.
    """
    if record.level <= 0:
        return []

    importer = Path(importer_path)

    # The importing file belongs to the package named by its parent directory.
    package_parts = list(importer.parent.parts)

    # One dot means the current package. Each extra dot moves up one level.
    levels_up = record.level - 1

    if levels_up > len(package_parts):
        return []

    if levels_up:
        package_parts = package_parts[:-levels_up]

    target_parts = package_parts.copy()

    if record.module:
        target_parts.extend(record.module.split("."))

    base_module = ".".join(target_parts)
    targets: list[Path] = []

    # Resolve the explicitly named module, e.g. `from .utils import helper`.
    if record.module and base_module in module_map:
        targets.append(module_map[base_module])

    # Resolve submodules, e.g. `from . import utils`.
    for name in record.names:
        if name == "*":
            continue

        candidate = ".".join(target_parts + [name])

        if candidate in module_map:
            targets.append(module_map[candidate])

    return list(dict.fromkeys(targets))
