
from pathlib import Path

from engine.entrypoints import detect_entrypoints
from engine.graph import DependencyGraph, build_dependency_graph
from engine.parse import parse_source
from engine.reading_path import generate_reading_path


def make_graph(edges, nodes):
    graph = DependencyGraph()

    for node in nodes:
        graph.imports_of[Path(node)] = set()
        graph.importers_of[Path(node)] = set()

    for source, target in edges:
        source = Path(source)
        target = Path(target)
        graph.imports_of[source].add(target)
        graph.importers_of[target].add(source)

    return graph


def test_path_follows_dependencies():
    graph = make_graph(
        [("main.py", "service.py"), ("service.py", "db.py")],
        ["main.py", "service.py", "db.py"],
    )

    result = generate_reading_path(graph, [Path("main.py")])

    assert [step.path for step in result] == [
        Path("main.py"),
        Path("service.py"),
        Path("db.py"),
    ]
    assert [step.order for step in result] == [1, 2, 3]


def test_preserves_supplied_entrypoint_priority_order():
    graph = make_graph(
        [],
        ["app.py", "cli.py", "main.py"],
    )

    result = generate_reading_path(
        graph,
        [Path("main.py"), Path("cli.py"), Path("app.py")],
    )

    assert [step.path for step in result] == [
        Path("main.py"),
        Path("cli.py"),
        Path("app.py"),
    ]


def test_duplicate_entrypoints_keep_first_priority_position():
    graph = make_graph(
        [],
        ["app.py", "main.py"],
    )

    result = generate_reading_path(
        graph,
        [Path("main.py"), Path("app.py"), Path("main.py")],
    )

    assert [step.path for step in result] == [
        Path("main.py"),
        Path("app.py"),
    ]


def test_uses_entrypoint_detection_priority_order():
    files = [
        parse_source("", Path("app.py")),
        parse_source("", Path("cli.py")),
        parse_source("", Path("main.py")),
        parse_source("", Path("helper.py")),
    ]

    graph = build_dependency_graph(files)
    entrypoints = detect_entrypoints(files, graph)

    assert entrypoints == [
        Path("main.py"),
        Path("cli.py"),
        Path("app.py"),
    ]

    result = generate_reading_path(graph, entrypoints)

    assert [step.path for step in result][:3] == entrypoints


def test_handles_cycles():
    graph = make_graph(
        [("a.py", "b.py"), ("b.py", "a.py")],
        ["a.py", "b.py"],
    )

    result = generate_reading_path(graph, [Path("a.py")])

    assert [step.path for step in result] == [
        Path("a.py"),
        Path("b.py"),
    ]


def test_respects_max_files():
    graph = make_graph(
        [("a.py", "b.py"), ("a.py", "c.py")],
        ["a.py", "b.py", "c.py"],
    )

    result = generate_reading_path(
        graph,
        [Path("a.py")],
        max_files=2,
    )

    assert len(result) == 2


def test_includes_disconnected_files():
    graph = make_graph(
        [("main.py", "service.py")],
        ["main.py", "service.py", "orphan.py"],
    )

    result = generate_reading_path(graph, [Path("main.py")])

    assert Path("orphan.py") in [step.path for step in result]


def test_empty_graph_returns_empty_path():
    graph = DependencyGraph()

    assert generate_reading_path(graph, []) == []


def test_non_positive_limit_returns_empty_path():
    graph = make_graph([], ["main.py"])

    assert generate_reading_path(
        graph,
        [Path("main.py")],
        max_files=0,
    ) == []
