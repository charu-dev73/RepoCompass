"""Parse Python source into structured facts, without executing it."""

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileInfo:
    path: Path
    line_count: int = 0
    docstring: str | None = None
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    parse_error: str | None = None


def parse_source(source: bytes | str, path: Path) -> FileInfo:
    """Parse source code into a FileInfo. Never raises on bad source."""
    info = FileInfo(path=Path(path), line_count=len(source.splitlines()))

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as exc:
        info.parse_error = f"{type(exc).__name__}: {exc}"
        return info

    docstring = ast.get_docstring(tree)
    if docstring:
        info.docstring = docstring.splitlines()[0]

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info.functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            info.classes.append(node.name)

    return info