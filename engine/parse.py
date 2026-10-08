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
    docstring: str | None = None
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)
    has_main_guard: bool = False
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
                        lineno=node.lineno,
                    )
                )

        elif isinstance(node, ast.ImportFrom):
            records.append(
                ImportRecord(
                    module=node.module,
                    lineno=node.lineno,
                    names=[alias.name for alias in node.names],
                    level=node.level,
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
            isinstance(operand, ast.Name)
            and operand.id == "__name__"
            for operand in operands
        )

        has_main = any(
            isinstance(operand, ast.Constant)
            and operand.value == "__main__"
            for operand in operands
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


MAX_FILE_BYTES = 1_000_000


def parse_file(root: Path, relative_path: Path) -> FileInfo:
    """Read one file under root and parse it."""
    relative_path = Path(relative_path)
    full_path = Path(root) / relative_path

    try:
        size = full_path.stat().st_size

        if size > MAX_FILE_BYTES:
            return FileInfo(
                path=relative_path,
                parse_error=(
                    f"FileTooLarge: {size} bytes "
                    f"(limit {MAX_FILE_BYTES})"
                ),
            )

        source = full_path.read_bytes()

    except OSError as exc:
        return FileInfo(
            path=relative_path,
            parse_error=f"{type(exc).__name__}: {exc}",
        )

    return parse_source(source, relative_path)


def parse_files(root: Path, relative_paths: list[Path]) -> list[FileInfo]:
    """Parse each file in the order given."""
    return [parse_file(root, path) for path in relative_paths]