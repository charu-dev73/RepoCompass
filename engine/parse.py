"""Parse Python source into structured facts, without executing it."""

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImportRecord:
    module: str | None  # "a.b" for "from a.b import c"; None for "from . import c"
    names: list[str] = field(default_factory=list)  # imported names; ["*"] for star
    level: int = 0  # leading dots of a relative import; 0 means absolute
    lineno: int = 0


@dataclass
class FileInfo:
    path: Path
    line_count: int = 0
    docstring: str | None = None  # first line of the module docstring
    functions: list[str] = field(default_factory=list)  # top-level only
    classes: list[str] = field(default_factory=list)  # top-level only
    imports: list[ImportRecord] = field(default_factory=list)
    parse_error: str | None = None


def _extract_imports(tree: ast.AST) -> list[ImportRecord]:
    """Collect every import statement in the tree, wherever it appears."""
    records = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append(ImportRecord(module=alias.name, lineno=node.lineno))
        elif isinstance(node, ast.ImportFrom):
            records.append(
                ImportRecord(
                    module=node.module,
                    names=[alias.name for alias in node.names],
                    level=node.level,
                    lineno=node.lineno,
                )
            )
    records.sort(key=lambda record: record.lineno)
    return records


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

    info.imports = _extract_imports(tree)

    return info