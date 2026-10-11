
from pathlib import Path

from engine.parse import ImportRecord
from engine.resolve import build_module_map, resolve_relative_import


MODULES = {
    "pkg": Path("pkg/__init__.py"),
    "pkg.main": Path("pkg/main.py"),
    "pkg.utils": Path("pkg/utils.py"),
    "pkg.models": Path("pkg/models.py"),
    "pkg.sub": Path("pkg/sub/__init__.py"),
    "pkg.sub.worker": Path("pkg/sub/worker.py"),
    "pkg.sub.helpers": Path("pkg/sub/helpers.py"),
}


def rec(module, names=(), level=1):
    return ImportRecord(
        module=module,
        names=list(names),
        level=level,
        lineno=1,
    )


def resolve(record, importer_path, module_map=MODULES):
    return resolve_relative_import(record, Path(importer_path), module_map)


def test_relative_import_from_same_package():
    assert resolve(
        rec("utils", ["helper"]),
        "pkg/main.py",
    ) == [Path("pkg/utils.py")]


def test_relative_import_of_submodule():
    assert resolve(
        rec(None, ["utils"]),
        "pkg/main.py",
    ) == [Path("pkg/utils.py")]


def test_relative_import_of_package_itself():
    assert resolve(
        rec(None, ["*"]),
        "pkg/main.py",
    ) == []


def test_parent_relative_import():
    assert resolve(
        rec("models", ["User"], level=2),
        "pkg/sub/worker.py",
    ) == [Path("pkg/models.py")]


def test_parent_relative_import_of_submodule():
    assert resolve(
        rec(None, ["helpers"], level=1),
        "pkg/sub/worker.py",
    ) == [Path("pkg/sub/helpers.py")]


def test_relative_import_from_init_file():
    assert resolve(
        rec(None, ["utils"]),
        "pkg/__init__.py",
    ) == [Path("pkg/utils.py")]


def test_absolute_import_is_ignored():
    assert resolve(
        rec("pkg.utils", ["helper"], level=0),
        "pkg/main.py",
    ) == []


def test_invalid_relative_import_above_package_root():
    assert resolve(
        rec("models", ["User"], level=4),
        "pkg/sub/worker.py",
    ) == []


def test_unknown_relative_module():
    assert resolve(
        rec("missing", ["helper"]),
        "pkg/main.py",
    ) == []


def test_module_map_supports_package_layout():
    module_map = build_module_map([
        Path("pkg/__init__.py"),
        Path("pkg/main.py"),
        Path("pkg/utils.py"),
    ])

    assert module_map["pkg"] == Path("pkg/__init__.py")
    assert module_map["pkg.main"] == Path("pkg/main.py")
    assert module_map["pkg.utils"] == Path("pkg/utils.py")
