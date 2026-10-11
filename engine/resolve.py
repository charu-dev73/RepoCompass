
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
            # The imported name may be defined or re-exported by this module.
            targets.append(base_path)

    return list(dict.fromkeys(targets))


def _get_importer_package(
    importer_path: Path,
    module_map: dict[str, Path],
) -> list[str]:
    """Determine the importer's package using its path in the module map."""
    importer = Path(importer_path)

    # Prefer the module name associated with the exact importing file.
    matching_names = [
        name
        for name, path in module_map.items()
        if Path(path) == importer
    ]

    if matching_names:
        module_name = max(matching_names, key=len)

        if importer.name == "__init__.py":
            return module_name.split(".")

        package_name = module_name.rpartition(".")[0]
        return package_name.split(".") if package_name else []

    # Fallback for an importer that is not present in the module map.
    parts = list(importer.parent.parts)

    # Source-root paths use module names relative to src/, not src.pkg.
    if parts and parts[0] == "src":
        parts = parts[1:]

    return parts


def resolve_relative_import(
    record: ImportRecord,
    importer_path: Path,
    module_map: dict[str, Path],
) -> list[Path]:
    """Resolve a relative import to repository files, if possible.

    importer_path must be relative to the repository root.
    """
    if record.level <= 0:
        return []

    package_parts = _get_importer_package(
        Path(importer_path),
        module_map,
    )

    # One dot means the current package.
    # Each additional dot moves up one package level.
    levels_up = record.level - 1

    # Moving above the top-level package is invalid.
    if levels_up > 0 and levels_up >= len(package_parts):
        return []

    if levels_up:
        package_parts = package_parts[:-levels_up]

    target_parts = package_parts.copy()

    if record.module:
        target_parts.extend(record.module.split("."))

    base_module = ".".join(target_parts)
    targets: list[Path] = []

    # For "from . import name", resolve actual sibling modules first.
    if record.module is None:
        if not base_module:
            return []

        for name in record.names:
            if name == "*":
                continue

            candidate = ".".join(target_parts + [name])

            if candidate in module_map:
                # A real sibling module takes priority over __init__.py.
                targets.append(module_map[candidate])

            elif (
                base_module in module_map
                and Path(module_map[base_module]).name == "__init__.py"
                and name not in module_map
            ):
                # The name may be defined or re-exported in __init__.py.
                # Do not mistake an unrelated root-level module for a
                # member of the current package.
                targets.append(module_map[base_module])

        return list(dict.fromkeys(targets))

    # For "from .module import name", resolve the explicit module and
    # then any imported submodules.
    base_path = module_map.get(base_module)

    if not record.names:
        return [base_path] if base_path is not None else []

    for name in record.names:
        if name == "*":
            continue

        candidate = f"{base_module}.{name}"

        if candidate in module_map:
            targets.append(module_map[candidate])

        elif base_path is not None:
            # The imported name may be defined in the explicit module.
            targets.append(base_path)

    return list(dict.fromkeys(targets))
