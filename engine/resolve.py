from pathlib import Path


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
