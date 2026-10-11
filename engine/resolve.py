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
    """Resolve an absolute import to repository files, if possible.

    Relative imports are handled separately and return an empty list here.
    """
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

    # Remove duplicates while preserving order.
    return list(dict.fromkeys(targets))
