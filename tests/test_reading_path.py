
from pathlib import Path

from engine.graph import DependencyGraph
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
