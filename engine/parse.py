"""Parse Python source into structured facts, without executing it."""

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImportRecord:
    module: str | None
    lineno: int = 0
    names: list[str] = field(default_factory=list)
    level: int = 0


@dataclass
class FileInfo:
    path: Path
    line_count: int = 0
    docstring: str | None = None  # first line of the module docstring
    functions: list[str] = field(default_factory=list)  # top-level only
    classes: list[str] = field(default_factory=list)  # top-level only
    imports: list[ImportRecord] = field(default_factory=list)
    has_main_guard: bool = False  # top-level `if __name__ == "__main__":`
    parse_error: str | None = None


def _extract_imports(tree: ast.AST) -> list[ImportRecord]:
    """Collect every import statement in the tree, wherever it appears."""
    records = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append(
                    ImportRecord(
                        module=alias.name,
                        names=[],
                        level=0,
                        lineno=node.lineno,
                    )
                )

        elif isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]

            records.append(
                ImportRecord(
                    module=node.module,
                    names=names,
                    level=node.level,
                    lineno=node.lineno,
                )
            )

    records.sort(key=lambda record: record.lineno)
    return records


def _has_main_guard(tree: ast.Module) -> bool:
    """True if the module has a top-level `if __name__ == "__main__":`."""
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue

        test = node.test

        if not isinstance(test, ast.Compare):
            continue

        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            continue

        operands = [test.left, test.comparators[0]]

        has_name = any(
            isinstance(o, ast.Name) and o.id == "__name__"
            for o in operands
        )

        has_main = any(
            isinstance(o, ast.Constant) and o.value == "__main__"
            for o in operands
        )

        if has_name and has_main:
            return True

    return False


def parse_source(source: bytes | str, path: Path) -> FileInfo:
    """Parse source code into a FileInfo. Never raises on bad source."""
    info = FileInfo(
        path=Path(path),
        line_count=len(source.splitlines()),
    )

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
    info.has_main_guard = _has_main_guard(tree)

    return info