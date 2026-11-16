
"""Find source and documentation files in an extracted repository."""

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

DOC_SKIP_DIRS = SKIP_DIRS | {
    ".github",
    ".readthedocs",
    "_build",
    "htmlcov",
}

DOC_EXTENSIONS = {".md", ".rst"}


@dataclass
class DiscoveryResult:
    python_files: list[Path] = field(default_factory=list)
    skipped_dirs: list[Path] = field(default_factory=list)


@dataclass
class DocDiscoveryResult:
    doc_files: list[Path] = field(default_factory=list)
    skipped_dirs: list[Path] = field(default_factory=list)


def _walk_files(
    root: Path,
    extensions: set[str],
    skip_dirs: set[str],
) -> tuple[list[Path], list[Path]]:
    """Walk a repository and collect files with selected extensions."""
    root = Path(root)
    found = []
    skipped = []

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        kept_dirs = []

        for name in sorted(dirs):
            if name in skip_dirs or name.endswith(".egg-info"):
                skipped.append(
                    (current_path / name).relative_to(root)
                )
            else:
                kept_dirs.append(name)

        dirs[:] = kept_dirs

        for name in files:
            if Path(name).suffix.lower() in extensions:
                found.append(
                    (current_path / name).relative_to(root)
                )

    found.sort()
    skipped.sort()

    return found, skipped


def find_python_files(root: Path) -> DiscoveryResult:
    """Find Python files, skipping folders we never analyse."""
    python_files, skipped_dirs = _walk_files(
        root,
        {".py"},
        SKIP_DIRS,
    )

    return DiscoveryResult(
        python_files=python_files,
        skipped_dirs=skipped_dirs,
    )


def find_doc_files(root: Path) -> DocDiscoveryResult:
    """Find Markdown, reStructuredText, and documentation text files."""
    root = Path(root)

    doc_files, skipped_dirs = _walk_files(
        root,
        DOC_EXTENSIONS | {".txt"},
        DOC_SKIP_DIRS,
    )

    # Only include .txt files inside directories named "docs".
    doc_files = [
        path
        for path in doc_files
        if path.suffix.lower() != ".txt"
        or "docs" in {
            part.lower() for part in path.parts[:-1]
        }
    ]

    return DocDiscoveryResult(
        doc_files=doc_files,
        skipped_dirs=skipped_dirs,
    )
