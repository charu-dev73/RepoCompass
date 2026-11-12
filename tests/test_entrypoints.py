
from pathlib import Path

from engine.entrypoints import detect_entrypoints
from engine.graph import build_dependency_graph
from engine.parse import parse_source


MAIN_GUARD = 'if __name__ == "__main__":\n    main()\n'


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


def test_package_main_module_is_an_entrypoint():
    files = [
        parse_file("pkg/__init__.py"),
        parse_file("pkg/__main__.py"),
    ]

    graph = build_dependency_graph(files)

    assert detect_entrypoints(files, graph) == [
        Path("pkg/__main__.py")
    ]


def test_imported_library_module_with_main_guard_is_not_an_entrypoint():
    files = [
        parse_file(
            "src/pkg/__init__.py",
            "from . import certs\nfrom . import help\n",
        ),
        parse_file("src/pkg/certs.py", MAIN_GUARD),
        parse_file("src/pkg/help.py", MAIN_GUARD),
    ]

    graph = build_dependency_graph(files)

    assert detect_entrypoints(files, graph) == []


def test_package_utility_with_main_guard_is_not_an_entrypoint():
    files = [
        parse_file("src/pkg/__init__.py"),
        parse_file("src/pkg/help.py", MAIN_GUARD),
        parse_file(
            "tests/test_help.py",
            "from pkg import help\n",
        ),
    ]

    graph = build_dependency_graph(files)

    assert detect_entrypoints(files, graph) == []


def test_library_init_file_is_not_promoted():
    files = [
        parse_file(
            "src/pkg/__init__.py",
            "from .core import run\n",
        ),
        parse_file("src/pkg/core.py", "def run():\n    pass\n"),
    ]

    graph = build_dependency_graph(files)

    assert detect_entrypoints(files, graph) == []


def test_application_main_ranks_above_imported_utility_guard():
    files = [
        parse_file(
            "app/main.py",
            "from . import helpers\n" + MAIN_GUARD,
        ),
        parse_file("app/helpers.py", MAIN_GUARD),
    ]

    graph = build_dependency_graph(files)

    assert detect_entrypoints(files, graph) == [
        Path("app/main.py")
    ]


def test_standalone_script_imported_only_by_tests_remains_an_entrypoint():
    files = [
        parse_file("scripts/start.py", MAIN_GUARD),
        parse_file(
            "tests/test_start.py",
            "import scripts.start\n",
        ),
    ]

    graph = build_dependency_graph(files)

    assert detect_entrypoints(files, graph) == [
        Path("scripts/start.py")
    ]


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
