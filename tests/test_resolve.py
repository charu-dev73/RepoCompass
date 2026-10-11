from pathlib import Path

from engine.resolve import build_module_map


def test_maps_regular_python_modules():
    paths = [
        Path("app.py"),
        Path("pkg/utils.py"),
    ]

    assert build_module_map(paths) == {
        "app": Path("app.py"),
        "pkg.utils": Path("pkg/utils.py"),
    }


def test_package_init_maps_to_package_name():
    paths = [
        Path("pkg/__init__.py"),
        Path("pkg/utils.py"),
    ]

    assert build_module_map(paths) == {
        "pkg": Path("pkg/__init__.py"),
        "pkg.utils": Path("pkg/utils.py"),
    }


def test_src_layout_maps_without_src_prefix():
    paths = [
        Path("src/flask/__init__.py"),
        Path("src/flask/app.py"),
    ]

    assert build_module_map(paths) == {
        "flask": Path("src/flask/__init__.py"),
        "flask.app": Path("src/flask/app.py"),
    }


def test_supports_namespace_packages():
    paths = [
        Path("pkg/tools/helper.py"),
    ]

    assert build_module_map(paths) == {
        "pkg.tools.helper": Path("pkg/tools/helper.py"),
    }


def test_ignores_non_python_files():
    paths = [
        Path("README.md"),
        Path("pkg/utils.py"),
    ]

    assert build_module_map(paths) == {
        "pkg.utils": Path("pkg/utils.py"),
    }
