from pathlib import Path

from engine.discover import find_python_files


def test_find_python_files_finds_python_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    (root / "app.py").write_text("print('app')")
    (root / "README.md").write_text("# Repo")

    src = root / "src"
    src.mkdir()
    (src / "main.py").write_text("print('main')")

    result = find_python_files(root)

    assert result.python_files == [
        Path("app.py"),
        Path("src/main.py"),
    ]


def test_find_python_files_skips_unwanted_directories(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    (root / "app.py").write_text("print('app')")

    venv = root / "venv"
    venv.mkdir()
    (venv / "bad.py").write_text("should not be found")

    node_modules = root / "node_modules"
    node_modules.mkdir()
    (node_modules / "bad.py").write_text("should not be found")

    git = root / ".git"
    git.mkdir()
    (git / "bad.py").write_text("should not be found")

    result = find_python_files(root)

    assert result.python_files == [Path("app.py")]

    assert sorted(result.skipped_dirs) == [
        Path(".git"),
        Path("node_modules"),
        Path("venv"),
    ]


def test_find_python_files_returns_relative_sorted_paths(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    z_dir = root / "zebra"
    z_dir.mkdir()
    (z_dir / "z.py").write_text("")

    a_dir = root / "alpha"
    a_dir.mkdir()
    (a_dir / "a.py").write_text("")

    (root / "m.py").write_text("")

    result = find_python_files(root)

    assert result.python_files == [
        Path("alpha/a.py"),
        Path("m.py"),
        Path("zebra/z.py"),
    ]


def test_find_python_files_skips_egg_info_directories(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    (root / "app.py").write_text("")

    metadata = root / "package.egg-info"
    metadata.mkdir()
    (metadata / "generated.py").write_text("")

    result = find_python_files(root)

    assert result.python_files == [Path("app.py")]
    assert result.skipped_dirs == [Path("package.egg-info")]