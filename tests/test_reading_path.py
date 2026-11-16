
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


def make_files(nodes, broken=()):
    broken = {str(Path(path)) for path in broken}
    files = []

    for node in nodes:
        info = parse_source("", Path(node))

        if str(Path(node)) in broken:
            info.parse_error = "SyntaxError: broken"

        files.append(info)

    return files


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


def test_library_without_entrypoints_starts_with_api_and_core_modules():
    nodes = [
        "src/library/__init__.py",
        "src/library/compat.py",
        "src/library/core.py",
        "src/library/service.py",
        "src/library/_types.py",
        "tests/test_service.py",
    ]
    graph = make_graph(
        [
            ("src/library/__init__.py", "src/library/compat.py"),
            ("src/library/__init__.py", "src/library/core.py"),
            ("src/library/__init__.py", "src/library/service.py"),
            ("src/library/compat.py", "src/library/_types.py"),
            ("src/library/core.py", "src/library/_types.py"),
            ("src/library/service.py", "src/library/core.py"),
            ("tests/test_service.py", "src/library/__init__.py"),
            ("tests/test_service.py", "src/library/core.py"),
            ("tests/test_service.py", "src/library/service.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )
    paths = [step.path for step in result]

    assert paths[0] == Path("src/library/__init__.py")
    assert paths[1] == Path("src/library/core.py")
    assert paths[2] == Path("src/library/service.py")
    assert paths.index(Path("src/library/core.py")) < paths.index(
        Path("src/library/_types.py")
    )
    assert paths[-1] == Path("tests/test_service.py")
    assert result[0].reason == "Package public API"
    assert result[1].reason == "Core implementation module"
    assert result[-1].reason == "Test demonstrating core behavior"


def test_secondary_example_leads_when_no_primary_entrypoint_exists():
    nodes = [
        "examples/demo.py",
        "src/library/__init__.py",
        "src/library/core.py",
        "tests/test_core.py",
    ]
    graph = make_graph(
        [
            ("examples/demo.py", "src/library/__init__.py"),
            ("examples/demo.py", "src/library/core.py"),
            ("src/library/__init__.py", "src/library/core.py"),
            ("tests/test_core.py", "src/library/__init__.py"),
            ("tests/test_core.py", "src/library/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        secondary_entrypoints=[Path("examples/demo.py")],
        file_infos=make_files(nodes),
    )

    assert result[0].path == Path("examples/demo.py")
    assert result[0].reason == "Example or supporting entry point"
    assert Path("src/library/__init__.py") in [
        step.path for step in result
    ]


def test_test_only_secondary_entrypoint_does_not_seed_library_path():
    nodes = [
        "src/library/__init__.py",
        "src/library/core.py",
        "tests/test_core.py",
    ]
    graph = make_graph(
        [
            ("src/library/__init__.py", "src/library/core.py"),
            ("tests/test_core.py", "src/library/__init__.py"),
            ("tests/test_core.py", "src/library/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        secondary_entrypoints=[Path("tests/test_core.py")],
        file_infos=make_files(nodes),
    )
    paths = [step.path for step in result]

    assert paths[0] == Path("src/library/__init__.py")
    assert paths[-1] == Path("tests/test_core.py")
    assert result[-1].reason == "Test demonstrating core behavior"


def test_multiple_core_modules_precede_low_level_dependencies():
    nodes = [
        "src/library/__init__.py",
        "src/library/core_a.py",
        "src/library/core_b.py",
        "src/library/core_c.py",
        "src/library/low_level.py",
        "tests/test_library.py",
    ]
    graph = make_graph(
        [
            ("src/library/__init__.py", "src/library/core_a.py"),
            ("src/library/__init__.py", "src/library/core_b.py"),
            ("src/library/__init__.py", "src/library/core_c.py"),
            ("src/library/core_a.py", "src/library/low_level.py"),
            ("src/library/core_b.py", "src/library/low_level.py"),
            ("src/library/core_c.py", "src/library/low_level.py"),
            ("tests/test_library.py", "src/library/__init__.py"),
            ("tests/test_library.py", "src/library/core_a.py"),
            ("tests/test_library.py", "src/library/core_b.py"),
            ("tests/test_library.py", "src/library/core_c.py"),
            ("tests/test_library.py", "src/library/low_level.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )
    paths = [step.path for step in result]
    low_level_index = paths.index(Path("src/library/low_level.py"))

    for core in ("core_a.py", "core_b.py", "core_c.py"):
        assert paths.index(Path("src/library") / core) < low_level_index


def test_test_imports_do_not_beat_public_api_and_core_modules():
    nodes = [
        "src/library/__init__.py",
        "src/library/core.py",
        "src/library/compat.py",
        "tests/test_a.py",
        "tests/test_b.py",
        "tests/test_c.py",
        "tests/test_d.py",
    ]
    graph = make_graph(
        [
            ("src/library/__init__.py", "src/library/core.py"),
            ("src/library/__init__.py", "src/library/compat.py"),
            ("src/library/core.py", "src/library/compat.py"),
            ("tests/test_a.py", "src/library/compat.py"),
            ("tests/test_a.py", "src/library/core.py"),
            ("tests/test_b.py", "src/library/compat.py"),
            ("tests/test_c.py", "src/library/compat.py"),
            ("tests/test_d.py", "src/library/compat.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )
    paths = [step.path for step in result]

    assert paths[0] == Path("src/library/__init__.py")
    assert paths[1] == Path("src/library/core.py")
    assert paths.index(Path("src/library/core.py")) < paths.index(
        Path("src/library/compat.py")
    )
    assert sum(path.name.startswith("test_") for path in paths) == 1


def test_parse_error_files_do_not_enter_library_path():
    nodes = [
        "src/library/__init__.py",
        "src/library/core.py",
        "src/library/broken.py",
        "tests/test_core.py",
    ]
    graph = make_graph(
        [
            ("src/library/__init__.py", "src/library/core.py"),
            ("src/library/core.py", "src/library/broken.py"),
            ("tests/test_core.py", "src/library/__init__.py"),
            ("tests/test_core.py", "src/library/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes, broken={"src/library/broken.py"}),
    )

    assert Path("src/library/broken.py") not in [
        step.path for step in result
    ]


def test_underscore_named_package_is_eligible_for_api_and_core():
    nodes = [
        "_pkg/__init__.py",
        "_pkg/core.py",
        "tests/test_core.py",
    ]
    graph = make_graph(
        [
            ("_pkg/__init__.py", "_pkg/core.py"),
            ("tests/test_core.py", "_pkg/__init__.py"),
            ("tests/test_core.py", "_pkg/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )
    paths = [step.path for step in result]

    assert paths[0] == Path("_pkg/__init__.py")
    assert result[0].reason == "Package public API"
    assert paths[1] == Path("_pkg/core.py")
    assert result[1].reason == "Core implementation module"


def test_multiple_package_roots_are_public_api_seeds():
    nodes = [
        "packages/alpha/__init__.py",
        "packages/alpha/core.py",
        "packages/beta/__init__.py",
        "packages/beta/core.py",
    ]
    graph = make_graph(
        [
            ("packages/alpha/__init__.py", "packages/alpha/core.py"),
            ("packages/beta/__init__.py", "packages/beta/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )
    api_paths = [
        step.path
        for step in result
        if step.reason == "Package public API"
    ]

    assert api_paths == [
        Path("packages/alpha/__init__.py"),
        Path("packages/beta/__init__.py"),
    ]


def test_namespace_package_uses_shallow_production_modules_as_api_seeds():
    nodes = [
        "packages/ns/alpha/core.py",
        "packages/ns/beta/core.py",
        "tests/test_core.py",
    ]
    graph = make_graph(
        [
            ("tests/test_core.py", "packages/ns/alpha/core.py"),
            ("tests/test_core.py", "packages/ns/beta/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )
    api_paths = [
        step.path
        for step in result
        if step.reason == "Package public API"
    ]

    assert api_paths == [
        Path("packages/ns/alpha/core.py"),
        Path("packages/ns/beta/core.py"),
    ]


def test_core_seed_diversity_spans_package_directories():
    nodes = [
        "packages/alpha/__init__.py",
        "packages/alpha/a.py",
        "packages/alpha/b.py",
        "packages/alpha/c.py",
        "packages/alpha/low.py",
        "packages/beta/__init__.py",
        "packages/beta/core.py",
    ]
    graph = make_graph(
        [
            ("packages/alpha/__init__.py", "packages/alpha/a.py"),
            ("packages/alpha/__init__.py", "packages/alpha/b.py"),
            ("packages/alpha/__init__.py", "packages/alpha/c.py"),
            ("packages/alpha/a.py", "packages/alpha/low.py"),
            ("packages/alpha/b.py", "packages/alpha/low.py"),
            ("packages/alpha/c.py", "packages/alpha/low.py"),
            ("packages/beta/__init__.py", "packages/beta/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )
    core_paths = [
        step.path
        for step in result
        if step.reason == "Core implementation module"
    ]

    assert Path("packages/alpha/a.py") in core_paths
    assert Path("packages/beta/core.py") in core_paths


def test_representative_test_does_not_displace_production_at_small_limit():
    nodes = [
        "src/library/__init__.py",
        "src/library/core.py",
        "src/library/prod_a.py",
        "src/library/prod_b.py",
        "src/library/prod_c.py",
        "src/library/prod_d.py",
        "tests/test_core.py",
    ]
    graph = make_graph(
        [
            ("src/library/__init__.py", "src/library/core.py"),
            ("src/library/core.py", "src/library/prod_a.py"),
            ("src/library/core.py", "src/library/prod_b.py"),
            ("src/library/core.py", "src/library/prod_c.py"),
            ("src/library/core.py", "src/library/prod_d.py"),
            ("tests/test_core.py", "src/library/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        max_files=5,
        file_infos=make_files(nodes),
    )

    assert len(result) == 5
    assert Path("tests/test_core.py") not in [
        step.path for step in result
    ]


def test_representative_test_omitted_when_dependencies_fill_slots():
    nodes = [
        "src/library/__init__.py",
        "src/library/core.py",
        "src/library/_types.py",
        "src/library/_helpers.py",
        "tests/test_core.py",
    ]
    graph = make_graph(
        [
            ("src/library/__init__.py", "src/library/core.py"),
            ("src/library/core.py", "src/library/_types.py"),
            ("src/library/core.py", "src/library/_helpers.py"),
            ("tests/test_core.py", "src/library/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        max_files=4,
        file_infos=make_files(nodes),
    )
    paths = [step.path for step in result]

    assert paths == [
        Path("src/library/__init__.py"),
        Path("src/library/core.py"),
        Path("src/library/_helpers.py"),
        Path("src/library/_types.py"),
    ]
    assert Path("tests/test_core.py") not in paths


def test_representative_test_prefers_multiple_core_modules():
    nodes = [
        "src/library/__init__.py",
        "src/library/core_a.py",
        "src/library/core_b.py",
        "src/library/core_c.py",
        "tests/test_one.py",
        "tests/test_two.py",
    ]
    graph = make_graph(
        [
            ("src/library/__init__.py", "src/library/core_a.py"),
            ("src/library/__init__.py", "src/library/core_b.py"),
            ("src/library/__init__.py", "src/library/core_c.py"),
            ("tests/test_one.py", "src/library/core_a.py"),
            ("tests/test_two.py", "src/library/core_a.py"),
            ("tests/test_two.py", "src/library/core_b.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )

    assert result[-1].path == Path("tests/test_two.py")
    assert result[-1].reason == "Test demonstrating core behavior"


def test_library_path_respects_max_files_at_boundaries():
    nodes = [
        "src/library/__init__.py",
        "src/library/core.py",
        "src/library/extra.py",
        "tests/test_core.py",
    ]
    graph = make_graph(
        [
            ("src/library/__init__.py", "src/library/core.py"),
            ("src/library/core.py", "src/library/extra.py"),
            ("tests/test_core.py", "src/library/core.py"),
        ],
        nodes,
    )

    for max_files in range(1, 9):
        result = generate_reading_path(
            graph,
            [],
            max_files=max_files,
            file_infos=make_files(nodes),
        )

        assert len(result) <= max_files


def test_multiple_secondary_entrypoints_are_kept_in_order():
    nodes = [
        "examples/one.py",
        "examples/two.py",
        "src/library/__init__.py",
        "src/library/core.py",
        "tests/test_core.py",
    ]
    graph = make_graph(
        [
            ("examples/one.py", "src/library/core.py"),
            ("examples/two.py", "src/library/core.py"),
            ("src/library/__init__.py", "src/library/core.py"),
            ("tests/test_core.py", "src/library/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        secondary_entrypoints=[
            Path("examples/one.py"),
            Path("examples/two.py"),
        ],
        file_infos=make_files(nodes),
    )

    assert [step.path for step in result[:2]] == [
        Path("examples/one.py"),
        Path("examples/two.py"),
    ]
    assert all(
        step.reason == "Example or supporting entry point"
        for step in result[:2]
    )


def test_generic_named_modules_remain_reachable():
    nodes = [
        "src/library/__init__.py",
        "src/library/core.py",
        "src/library/types.py",
        "src/library/utils/helpers.py",
        "tests/test_core.py",
    ]
    graph = make_graph(
        [
            ("src/library/__init__.py", "src/library/core.py"),
            ("src/library/core.py", "src/library/types.py"),
            ("src/library/core.py", "src/library/utils/helpers.py"),
            ("tests/test_core.py", "src/library/core.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )
    paths = [step.path for step in result]

    assert Path("src/library/types.py") in paths
    assert Path("src/library/utils/helpers.py") in paths


def test_requests_like_library_path_keeps_api_and_core_first():
    nodes = [
        "src/requests/__init__.py",
        "src/requests/models.py",
        "src/requests/sessions.py",
        "src/requests/api.py",
        "src/requests/compat.py",
        "src/requests/_types.py",
        "tests/test_requests.py",
    ]
    graph = make_graph(
        [
            ("src/requests/__init__.py", "src/requests/models.py"),
            ("src/requests/__init__.py", "src/requests/sessions.py"),
            ("src/requests/__init__.py", "src/requests/api.py"),
            ("src/requests/__init__.py", "src/requests/compat.py"),
            ("src/requests/models.py", "src/requests/_types.py"),
            ("src/requests/models.py", "src/requests/compat.py"),
            ("tests/test_requests.py", "src/requests/__init__.py"),
            ("tests/test_requests.py", "src/requests/models.py"),
            ("tests/test_requests.py", "src/requests/sessions.py"),
            ("tests/test_requests.py", "src/requests/api.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )
    paths = [step.path for step in result]

    assert paths[0] == Path("src/requests/__init__.py")
    assert Path("src/requests/models.py") in paths[:4]
    assert Path("src/requests/sessions.py") in paths[:4]
    assert Path("src/requests/api.py") in paths[:4]
    assert paths.index(Path("src/requests/compat.py")) > 3
    assert paths[-1] == Path("tests/test_requests.py")


def test_scikit_like_library_path_prefers_package_apis_over_utils():
    nodes = [
        "sklearn/__init__.py",
        "sklearn/base.py",
        "sklearn/preprocessing/__init__.py",
        "sklearn/metrics/__init__.py",
        "sklearn/datasets/__init__.py",
        "sklearn/utils/validation.py",
        "sklearn/tests/test_base.py",
    ]
    graph = make_graph(
        [
            ("sklearn/__init__.py", "sklearn/base.py"),
            ("sklearn/__init__.py", "sklearn/preprocessing/__init__.py"),
            ("sklearn/__init__.py", "sklearn/metrics/__init__.py"),
            ("sklearn/tests/test_base.py", "sklearn/__init__.py"),
            ("sklearn/tests/test_base.py", "sklearn/utils/validation.py"),
            ("sklearn/preprocessing/__init__.py", "sklearn/utils/validation.py"),
            ("sklearn/metrics/__init__.py", "sklearn/utils/validation.py"),
        ],
        nodes,
    )

    result = generate_reading_path(
        graph,
        [],
        file_infos=make_files(nodes),
    )
    paths = [step.path for step in result]
    utils_index = paths.index(Path("sklearn/utils/validation.py"))

    assert paths[0] == Path("sklearn/__init__.py")
    assert Path("sklearn/base.py") in paths[:4]
    assert paths.index(Path("sklearn/preprocessing/__init__.py")) < utils_index
    assert paths.index(Path("sklearn/metrics/__init__.py")) < utils_index
