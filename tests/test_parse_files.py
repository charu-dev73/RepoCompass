from pathlib import Path

from engine import parse as parse_module
from engine.parse import parse_file, parse_files


def write(root, name, content):
    """Create a file (and any parent folders) under root."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        content if isinstance(content, bytes) else content.encode()
    )
    return path


def test_parse_file_reads_and_parses_relative_to_root(tmp_path):
    write(
        tmp_path,
        "pkg/app.py",
        '"""App entry."""\n\ndef run():\n    pass\n',
    )

    info = parse_file(tmp_path, Path("pkg/app.py"))

    assert info.path == Path("pkg/app.py")
    assert info.docstring == "App entry."
    assert info.functions == ["run"]
    assert info.parse_error is None


def test_missing_file_is_recorded_not_raised(tmp_path):
    info = parse_file(tmp_path, Path("nope.py"))

    assert info.path == Path("nope.py")
    assert info.parse_error.startswith("FileNotFoundError")


def test_file_over_size_limit_is_not_parsed(monkeypatch, tmp_path):
    monkeypatch.setattr(parse_module, "MAX_FILE_BYTES", 10)
    write(tmp_path, "big.py", "def f():\n    pass\n")

    info = parse_file(tmp_path, Path("big.py"))

    assert info.parse_error.startswith("FileTooLarge")
    assert info.functions == []


def test_one_bad_file_does_not_affect_the_others(tmp_path):
    write(tmp_path, "a.py", "def a():\n    pass\n")
    write(tmp_path, "b.py", "def broken(:\n")
    write(tmp_path, "c.py", "class C:\n    pass\n")

    paths = [Path("a.py"), Path("b.py"), Path("c.py")]
    infos = parse_files(tmp_path, paths)

    assert [info.path for info in infos] == paths
    assert infos[0].functions == ["a"]
    assert infos[1].parse_error.startswith("SyntaxError")
    assert infos[2].classes == ["C"]


def test_invalid_utf8_without_declaration_is_a_parse_error(tmp_path):
    write(tmp_path, "latin.py", b"x = '\xe9'\n")

    info = parse_file(tmp_path, Path("latin.py"))

    assert info.parse_error is not None


def test_declared_encoding_is_respected(tmp_path):
    write(
        tmp_path,
        "latin.py",
        b"# -*- coding: latin-1 -*-\nx = '\xe9'\n",
    )

    info = parse_file(tmp_path, Path("latin.py"))

    assert info.parse_error is None