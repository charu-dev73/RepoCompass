"""Find the Python files in an extracted repository."""

import os
from dataclasses import dataclass, field
from pathlib import Path


SKIP_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "site-packages",
    "build",
    "dist",
    "__pycache__",
    ".tox",
    "vendor",
    "third_party",
}


@dataclass
class DiscoveryResult:
    python_files: list[Path] = field(default_factory=list)
    skipped_dirs: list[Path] = field(default_factory=list)


def find_python_files(root: Path) -> DiscoveryResult:
    """Walk root and collect .py files, skipping folders we never analyse."""

    root = Path(root)
    result = DiscoveryResult()

    for current, dirs, files in os.walk(root):
        current_path = Path(current)

        kept = []

        for name in sorted(dirs):
            if name in SKIP_DIRS or name.endswith(".egg-info"):
                result.skipped_dirs.append(
                    (current_path / name).relative_to(root)
                )
            else:
                kept.append(name)

        # Prune skipped directories.
        dirs[:] = kept

        for name in files:
            if name.endswith(".py"):
                result.python_files.append(
                    (current_path / name).relative_to(root)
                )

    # Make results deterministic regardless of filesystem traversal order.
    result.python_files.sort()
    result.skipped_dirs.sort()

    return result