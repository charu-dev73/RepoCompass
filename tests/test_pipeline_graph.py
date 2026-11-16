
from pathlib import Path

from engine.pipeline import RepoSnapshot, load_repository


def test_repo_snapshot_has_an_empty_graph_by_default():
    snapshot = RepoSnapshot(
        owner="example",
        repo="example",
        root=Path("."),
        discovery=None,
        files=[],
    )

    assert snapshot.graph.nodes() == []
    assert snapshot.graph.edges() == []

def test_load_repository_builds_dependency_graph(
    tmp_path,
    monkeypatch,
):
    import engine.pipeline as pipeline

    # Create a small fake repository.
    repo_root = tmp_path / "fake_repo"
    repo_root.mkdir()

    (repo_root / "app.py").write_text(
        "import services\n",
        encoding="utf-8",
    )

    (repo_root / "services.py").write_text(
        "def hello():\n    return 'hello'\n",
        encoding="utf-8",
    )

    # Avoid downloading anything from GitHub.
    monkeypatch.setattr(
        pipeline,
        "download_repo_zip",
        lambda owner, repo, workdir: tmp_path / "fake.zip",
    )

    monkeypatch.setattr(
        pipeline,
        "extract_repo_zip",
        lambda zip_path, destination: repo_root,
    )

    snapshot = load_repository(
        "https://github.com/example/example",
        tmp_path,
    )

    assert snapshot.graph.nodes() == [
        Path("app.py"),
        Path("services.py"),
    ]

    assert snapshot.graph.edges() == [
        (Path("app.py"), Path("services.py")),
    ]

    assert snapshot.graph.in_degree(Path("services.py")) == 1
    assert snapshot.graph.out_degree(Path("app.py")) == 1


def test_repo_snapshot_has_empty_entrypoints_by_default():
    snapshot = RepoSnapshot(
        owner="example",
        repo="example",
        root=Path("."),
        discovery=None,
        files=[],
    )

    assert snapshot.entrypoints == []

def test_load_repository_detects_entrypoints(
    tmp_path,
    monkeypatch,
):
    import engine.pipeline as pipeline

    repo_root = tmp_path / "fake_repo"
    repo_root.mkdir()

    (repo_root / "main.py").write_text(
        'if __name__ == "__main__":\n    print("hello")\n',
        encoding="utf-8",
    )

    (repo_root / "helper.py").write_text(
        "def hello():\n    return 'hello'\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        pipeline,
        "download_repo_zip",
        lambda owner, repo, workdir: tmp_path / "fake.zip",
    )

    monkeypatch.setattr(
        pipeline,
        "extract_repo_zip",
        lambda zip_path, destination: repo_root,
    )

    snapshot = load_repository(
        "https://github.com/example/example",
        tmp_path,
    )

    assert Path("main.py") in snapshot.entrypoints

def test_repo_snapshot_has_empty_reading_path_by_default():
    snapshot = RepoSnapshot(
        owner="example",
        repo="example",
        root=Path("."),
        discovery=None,
        files=[],
    )

    assert snapshot.reading_path == []

def test_load_repository_generates_reading_path(
    tmp_path,
    monkeypatch,
):
    import engine.pipeline as pipeline

    repo_root = tmp_path / "fake_repo"
    repo_root.mkdir()

    (repo_root / "main.py").write_text(
        "import services\n"
        'if __name__ == "__main__":\n'
        '    print("hello")\n',
        encoding="utf-8",
    )

    (repo_root / "services.py").write_text(
        "def hello():\n"
        "    return 'hello'\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        pipeline,
        "download_repo_zip",
        lambda owner, repo, workdir: tmp_path / "fake.zip",
    )

    monkeypatch.setattr(
        pipeline,
        "extract_repo_zip",
        lambda zip_path, destination: repo_root,
    )

    snapshot = load_repository(
        "https://github.com/example/example",
        tmp_path,
    )

    paths = [step.path for step in snapshot.reading_path]

    assert paths
    assert paths[0] == Path("main.py")
    assert Path("services.py") in paths
    assert [step.order for step in snapshot.reading_path] == list(
        range(1, len(snapshot.reading_path) + 1)
    )


def test_load_repository_separates_secondary_entrypoints(
    tmp_path,
    monkeypatch,
):
    import engine.pipeline as pipeline

    repo_root = tmp_path / "fake_repo"
    repo_root.mkdir()
    fixture = repo_root / "tests/test_apps/cliapp/app.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("app = None\n", encoding="utf-8")
    (repo_root / "app.py").write_text("app = None\n", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "download_repo_zip",
        lambda owner, repo, workdir: tmp_path / "fake.zip",
    )

    monkeypatch.setattr(
        pipeline,
        "extract_repo_zip",
        lambda zip_path, destination: repo_root,
    )

    snapshot = load_repository(
        "https://github.com/example/example",
        tmp_path,
    )

    assert snapshot.entrypoints == [Path("app.py")]
    assert snapshot.secondary_entrypoints == [
        Path("tests/test_apps/cliapp/app.py")
    ]


def test_uses_secondary_entrypoints_when_no_primary_exists(
    tmp_path,
    monkeypatch,
):
    import engine.pipeline as pipeline

    repo_root = tmp_path / "fake_repo"
    repo_root.mkdir()
    example = repo_root / "examples/demo.py"
    example.parent.mkdir()
    example.write_text(
        'if __name__ == "__main__":\n    print("demo")\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        pipeline,
        "download_repo_zip",
        lambda owner, repo, workdir: tmp_path / "fake.zip",
    )

    monkeypatch.setattr(
        pipeline,
        "extract_repo_zip",
        lambda zip_path, destination: repo_root,
    )

    snapshot = load_repository(
        "https://github.com/example/example",
        tmp_path,
    )

    assert snapshot.entrypoints == []
    assert snapshot.secondary_entrypoints == [Path("examples/demo.py")]
    assert snapshot.reading_path[0].path == Path("examples/demo.py")


def test_load_repository_builds_library_reading_path(
    tmp_path,
    monkeypatch,
):
    import engine.pipeline as pipeline

    repo_root = tmp_path / "fake_repo"
    package = repo_root / "library"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from . import core\n",
        encoding="utf-8",
    )
    (package / "core.py").write_text(
        "def work():\n"
        "    return 'work'\n",
        encoding="utf-8",
    )
    tests = repo_root / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text(
        "import library\n"
        "from library import core\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        pipeline,
        "download_repo_zip",
        lambda owner, repo, workdir: tmp_path / "fake.zip",
    )

    monkeypatch.setattr(
        pipeline,
        "extract_repo_zip",
        lambda zip_path, destination: repo_root,
    )

    snapshot = load_repository(
        "https://github.com/example/example",
        tmp_path,
    )
    paths = [step.path for step in snapshot.reading_path]

    assert snapshot.entrypoints == []
    assert paths[0] == Path("library/__init__.py")
    assert Path("library/core.py") in paths
    assert snapshot.reading_path[0].reason == "Package public API"
