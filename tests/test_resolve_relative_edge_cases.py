
from pathlib import Path

import pytest

from engine.parse import ImportRecord
from engine.resolve import (
    build_module_map,
    resolve_absolute_import,
    resolve_relative_import,
)


def rec(module, names=(), level=1):
    """Build an ImportRecord the way the parser would."""
    return ImportRecord(
        module=module,
        names=list(names),
        level=level,
        lineno=1,
    )


def paths(*names):
    return [Path(name) for name in names]


REPO = paths(
    "pkg/__init__.py",
    "pkg/mod.py",
    "pkg/x.py",
    "pkg/sub/__init__.py",
    "pkg/sub/deep.py",
    "top.py",
    "z.py",
    "util.py",
)


def resolve_rel(importer, record, files=REPO):
    module_map = build_module_map(files)
    return resolve_relative_import(record, Path(importer), module_map)


@pytest.mark.parametrize(
    "importer, record, expected",
    [
        pytest.param(
            "pkg/mod.py", rec(None, ["x"]), paths("pkg/x.py"),
            id="01-sibling-from-module",
        ),
        pytest.param(
            "pkg/__init__.py", rec(None, ["x"]), paths("pkg/x.py"),
            id="02-from-init-file",
        ),
        pytest.param(
            "pkg/sub/deep.py", rec(None, ["x"], 2), paths("pkg/x.py"),
            id="03-one-level-up",
        ),
        pytest.param(
            "pkg/sub/__init__.py", rec(None, ["x"], 2), paths("pkg/x.py"),
            id="04-one-level-up-from-init",
        ),
        pytest.param(
            "pkg/sub/deep.py", rec(None, ["z"], 3), [],
            id="05-beyond-top-level",
        ),
        pytest.param(
            "pkg/mod.py", rec(None, ["z"], 2), [],
            id="05b-beyond-top-level-one-package-deep",
        ),
        pytest.param(
            "top.py", rec(None, ["util"], 1), [],
            id="06-top-level-script-has-no-package",
        ),
        pytest.param(
            "top.py", rec(None, ["util"], 2), [],
            id="06b-top-level-script-two-dots",
        ),
        pytest.param(
            "pkg/mod.py", rec("sub", ["deep"]), paths("pkg/sub/deep.py"),
            id="07-submodule-via-relative-base",
        ),
        pytest.param(
            "pkg/mod.py", rec("sub.deep", ["f"]), paths("pkg/sub/deep.py"),
            id="08-dotted-relative-module",
        ),
        pytest.param(
            "pkg/mod.py", rec(None, ["helper"]), paths("pkg/__init__.py"),
            id="09-name-defined-in-init",
        ),
        pytest.param(
            "pkg/mod.py", rec(None, ["*"]), [],
            id="10-star-import",
        ),
        pytest.param(
            "pkg/mod.py", rec("missing", ["f"]), [],
            id="11-missing-module",
        ),
        pytest.param(
            "pkg/mod.py", rec(None, ["util"]), [],
            id="12-relative-never-matches-root-module",
        ),
    ],
)
def test_relative_import_semantics(importer, record, expected):
    assert resolve_rel(importer, record) == expected


def test_13_src_layout_relative_import():
    files = paths(
        "src/pkg/__init__.py",
        "src/pkg/mod.py",
        "src/pkg/x.py",
    )

    assert resolve_rel(
        "src/pkg/mod.py",
        rec(None, ["x"]),
        files,
    ) == paths("src/pkg/x.py")


def test_14_namespace_package_without_init():
    files = paths("ns/a.py", "ns/b.py")

    assert resolve_rel(
        "ns/a.py",
        rec(None, ["b"]),
        files,
    ) == paths("ns/b.py")


def test_15_package_comes_from_importer_path_when_module_names_are_duplicated():
    files = paths(
        "pkg/a.py",
        "src/pkg/a.py",
        "pkg/x.py",
    )

    assert resolve_rel(
        "pkg/a.py",
        rec(None, ["x"]),
        files,
    ) == paths("pkg/x.py")


@pytest.mark.parametrize(
    "importer, relative, absolute",
    [
        pytest.param(
            "pkg/mod.py",
            rec("sub", ["deep"]),
            rec("pkg.sub", ["deep"], 0),
            id="submodule",
        ),
        pytest.param(
            "pkg/mod.py",
            rec("sub.deep", ["f"]),
            rec("pkg.sub.deep", ["f"], 0),
            id="dotted-module",
        ),
        pytest.param(
            "pkg/mod.py",
            rec(None, ["helper"]),
            rec("pkg", ["helper"], 0),
            id="name-in-init",
        ),
        pytest.param(
            "pkg/sub/deep.py",
            rec(None, ["x"], 2),
            rec("pkg", ["x"], 0),
            id="one-level-up",
        ),
    ],
)
def test_relative_import_matches_its_absolute_equivalent(
    importer, relative, absolute
):
    module_map = build_module_map(REPO)

    assert resolve_relative_import(
        relative, Path(importer), module_map
    ) == resolve_absolute_import(absolute, module_map)
