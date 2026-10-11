
from pathlib import Path

from engine.parse import ImportRecord, parse_source
from engine.resolve import build_module_map, resolve_absolute_import

MODULES = {
    "util": Path("util.py"),
    "app": Path("app.py"),
    "a": Path("a/__init__.py"),
    "a.b": Path("a/b/__init__.py"),
    "a.b.c": Path("a/b/c.py"),
    "pkg": Path("pkg/__init__.py"),
    "pkg.mod_a": Path("pkg/mod_a.py"),
    "ns.mod": Path("ns/mod.py"),
}


def rec(module, names=(), level=0):
    """Build an ImportRecord the way the parser does."""
    return ImportRecord(
        module=module,
        names=list(names),
        level=level,
        lineno=1,
    )


def resolve(record, module_map=MODULES):
    return resolve_absolute_import(record, module_map)


def test_plain_import_resolves_to_exact_module():
    assert resolve(rec("a.b")) == [Path("a/b/__init__.py")]


def test_plain_import_links_only_the_deepest_module():
    assert resolve(rec("a.b.c")) == [Path("a/b/c.py")]


def test_plain_import_falls_back_to_longest_existing_prefix():
    assert resolve(rec("a.b.missing")) == [Path("a/b/__init__.py")]


def test_plain_import_of_top_level_module_file():
    assert resolve(rec("util")) == [Path("util.py")]


def test_external_import_resolves_to_nothing():
    assert resolve(rec("requests")) == []


def test_prefix_matching_uses_dotted_parts():
    assert resolve(rec("apple")) == []
    assert resolve(rec("app")) == [Path("app.py")]


def test_from_import_of_submodule_points_at_submodule():
    assert resolve(rec("a", ["b"])) == [Path("a/b/__init__.py")]


def test_from_import_of_name_points_at_defining_module():
    assert resolve(rec("a.b", ["helper"])) == [Path("a/b/__init__.py")]


def test_from_import_mixing_submodule_and_name():
    assert resolve(rec("pkg", ["mod_a", "helper"])) == [
        Path("pkg/mod_a.py"),
        Path("pkg/__init__.py"),
    ]


def test_from_import_duplicates_are_collapsed():
    assert resolve(rec("a", ["x", "y"])) == [Path("a/__init__.py")]


def test_star_import_points_at_module():
    assert resolve(rec("a", ["*"])) == [Path("a/__init__.py")]


def test_namespace_package_submodule():
    assert resolve(rec("ns", ["mod"])) == [Path("ns/mod.py")]


def test_from_import_of_external_module_resolves_to_nothing():
    assert resolve(rec("requests", ["get"])) == []


def test_from_import_falls_back_to_existing_parent():
    assert resolve(rec("pkg._speedups", ["fast"])) == [
        Path("pkg/__init__.py")
    ]


def test_relative_imports_are_left_for_later():
    assert resolve(rec(None, ["x"], level=1)) == []
    assert resolve(rec("util", ["f"], level=1)) == []


def test_future_import_is_not_internal():
    assert resolve(rec("__future__", ["annotations"])) == []


def test_resolution_with_src_layout_module_map():
    module_map = build_module_map([
        Path("src/flask/__init__.py"),
        Path("src/flask/app.py"),
        Path("tests/test_app.py"),
    ])

    assert resolve(rec("flask"), module_map) == [
        Path("src/flask/__init__.py")
    ]
    assert resolve(rec("flask.app", ["Flask"]), module_map) == [
        Path("src/flask/app.py")
    ]
    assert resolve(rec("flask", ["app"]), module_map) == [
        Path("src/flask/app.py")
    ]


def test_resolution_of_records_produced_by_parser():
    module_map = build_module_map([
        Path("pkg/__init__.py"),
        Path("pkg/util.py"),
        Path("pkg/helper.py"),
    ])

    records = parse_source(
        "import os\nimport pkg.util\nfrom pkg import helper\n",
        Path("main.py"),
    ).imports

    assert [resolve(record, module_map) for record in records] == [
        [],
        [Path("pkg/util.py")],
        [Path("pkg/helper.py")],
    ]
