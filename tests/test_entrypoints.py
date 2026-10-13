
from pathlib import Path

from engine.entrypoints import detect_entrypoints
from engine.parse import parse_source


def parse_file(path, source=""):
    return parse_source(source, Path(path))


def test_detects_common_entrypoint_names():
    files = [
        parse_file("helper.py"),
        parse_file("app.py"),
        parse_file("main.py"),
        parse_file("cli.py"),
    ]

    assert detect_entrypoints(files) == [
        Path("main.py"),
        Path("cli.py"),
        Path("app.py"),
    ]


def test_detects_main_guard():
    files = [
        parse_file(
            "scripts/start.py",
            'if __name__ == "__main__":\n    print("hello")\n',
        ),
        parse_file("helper.py"),
    ]

    assert detect_entrypoints(files) == [Path("scripts/start.py")]


def test_ignores_files_with_parse_errors():
    info = parse_file("main.py", "def broken(:\n")
    assert info.parse_error is not None

    assert detect_entrypoints([info]) == []


def test_returns_deterministic_order_for_equal_scores():
    files = [
        parse_file("z/main.py"),
        parse_file("a/main.py"),
    ]

    assert detect_entrypoints(files) == [
        Path("a/main.py"),
        Path("z/main.py"),
    ]


def test_no_entrypoints_returns_empty_list():
    files = [parse_file("helper.py")]

    assert detect_entrypoints(files) == []
