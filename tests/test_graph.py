
from pathlib import Path

from engine.graph import build_dependency_graph
from engine.parse import FileInfo, parse_source


def make_file(path, source="", parse_error=None):
    info = parse_source(source, Path(path))
    info.parse_error = parse_error
    return info


def test_builds_import_edges():
    files = [
        make_file("app.py", "import services"),
        make_file("services.py", "import database"),
        make_file("database.py"),
    ]

    graph = build_dependency_graph(files)

    assert graph.imports_of[Path("app.py")] == {
        Path("services.py")
    }
    assert graph.imports_of[Path("services.py")] == {
        Path("database.py")
    }
    assert graph.importers_of[Path("database.py")] == {
        Path("services.py")
    }


def test_includes_files_without_imports():
    files = [
        make_file("app.py", "import services"),
        make_file("services.py"),
        make_file("unused.py"),
    ]

    graph = build_dependency_graph(files)

    assert set(graph.nodes()) == {
        Path("app.py"),
        Path("services.py"),
        Path("unused.py"),
    }
    assert graph.imports_of[Path("unused.py")] == set()


def test_duplicate_imports_create_one_edge():
    files = [
        make_file(
            "app.py",
            "import services\nimport services\n",
        ),
        make_file("services.py"),
    ]

    graph = build_dependency_graph(files)

    assert graph.edges() == [
        (Path("app.py"), Path("services.py"))
    ]


def test_supports_circular_dependencies():
    files = [
        make_file("a.py", "import b"),
        make_file("b.py", "import a"),
    ]

    graph = build_dependency_graph(files)

    assert graph.edges() == [
        (Path("a.py"), Path("b.py")),
        (Path("b.py"), Path("a.py")),
    ]
    assert graph.in_degree(Path("a.py")) == 1
    assert graph.in_degree(Path("b.py")) == 1


def test_parse_error_file_remains_a_node():
    files = [
        make_file("app.py", "import broken"),
        make_file("broken.py", parse_error="SyntaxError"),
    ]

    graph = build_dependency_graph(files)

    assert Path("broken.py") in graph.nodes()
    assert graph.importers_of[Path("broken.py")] == {
        Path("app.py")
    }
    assert graph.imports_of[Path("broken.py")] == set()


def test_ignores_external_imports():
    files = [
        make_file("app.py", "import requests\nimport os"),
    ]

    graph = build_dependency_graph(files)

    assert graph.nodes() == [Path("app.py")]
    assert graph.edges() == []


def test_empty_repository():
    graph = build_dependency_graph([])

    assert graph.nodes() == []
    assert graph.edges() == []
