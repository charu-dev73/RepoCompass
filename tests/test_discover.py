from pathlib import Path

from engine.discover import find_python_files


def make_files(root, names):
    """Create empty files, making parent folders as needed."""
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")


def test_finds_only_python_files(tmp_path):
    make_files(
        tmp_path,
        [
            "app.py",
            "README.md",
            "pkg/util.py",
            "pkg/data.json",
        ],
    )

    result = find_python_files(tmp_path)

    assert result.python_files == [
        Path("app.py"),
        Path("pkg/util.py"),
    ]


def test_paths_are_relative_path_objects(tmp_path):
    make_files(tmp_path, ["src/main.py"])

    result = find_python_files(tmp_path)

    assert result.python_files == [Path("src/main.py")]
    assert all(isinstance(path, Path) for path in result.python_files)


def test_skips_unwanted_directories(tmp_path):
    make_files(
        tmp_path,
        [
            "app.py",
            "venv/bad.py",
            "node_modules/bad.py",
            "build/bad.py",
        ],
    )

    result = find_python_files(tmp_path)

    assert result.python_files == [Path("app.py")]

    assert sorted(result.skipped_dirs) == [
        Path("build"),
        Path("node_modules"),
        Path("venv"),
    ]


def test_skips_nested_unwanted_directories(tmp_path):
    make_files(
        tmp_path,
        [
            "src/main.py",
            "src/pkg/vendor/x.py",
        ],
    )

    result = find_python_files(tmp_path)

    assert result.python_files == [Path("src/main.py")]
    assert result.skipped_dirs == [Path("src/pkg/vendor")]


def test_skips_egg_info_directories(tmp_path):
    make_files(
        tmp_path,
        [
            "app.py",
            "package.egg-info/generated.py",
        ],
    )

    result = find_python_files(tmp_path)

    assert result.python_files == [Path("app.py")]
    assert result.skipped_dirs == [Path("package.egg-info")]


def test_empty_directory_returns_empty_lists(tmp_path):
    result = find_python_files(tmp_path)

    assert result.python_files == []
    assert result.skipped_dirs == []


def test_build_python_file_is_kept(tmp_path):
    make_files(
        tmp_path,
        [
            "build.py",
            "src/build.py",
        ],
    )

    result = find_python_files(tmp_path)

    assert result.python_files == [
        Path("build.py"),
        Path("src/build.py"),
    ]


def test_python_files_are_sorted_deterministically(tmp_path):
    make_files(
        tmp_path,
        [
            "z.py",
            "a/b.py",
            "m.py",
        ],
    )

    result = find_python_files(tmp_path)

    assert result.python_files == [
        Path("a/b.py"),
        Path("m.py"),
        Path("z.py"),
    ]


def test_skipped_dirs_are_sorted_deterministically(tmp_path):
    make_files(
        tmp_path,
        [
            "venv/a.py",
            "build/b.py",
            "node_modules/c.py",
        ],
    )

    result = find_python_files(tmp_path)

    assert result.skipped_dirs == [
        Path("build"),
        Path("node_modules"),
        Path("venv"),
    ]