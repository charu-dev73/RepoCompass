import zipfile
from pathlib import Path

import pytest

from engine import pipeline
from engine.fetch import InvalidGitHubURL


def make_repo_zip(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("pallets-flask-abc123/app.py", "")
        archive.writestr("pallets-flask-abc123/pkg/util.py", "")
        archive.writestr("pallets-flask-abc123/README.md", "")
        archive.writestr("pallets-flask-abc123/venv/lib.py", "")


def test_load_repository_runs_the_full_chain(monkeypatch, tmp_path):
    def fake_download(owner, repo, dest_dir):
        zip_path = dest_dir / "repo.zip"
        make_repo_zip(zip_path)
        return zip_path

    monkeypatch.setattr(pipeline, "download_repo_zip", fake_download)

    snapshot = pipeline.load_repository(
        "https://github.com/pallets/flask",
        tmp_path,
    )

    assert (snapshot.owner, snapshot.repo) == ("pallets", "flask")
    assert snapshot.discovery.python_files == [
        Path("app.py"),
        Path("pkg/util.py"),
    ]
    assert snapshot.discovery.skipped_dirs == [Path("venv")]


def test_invalid_url_fails_before_any_download(monkeypatch, tmp_path):
    def must_not_be_called(*args, **kwargs):
        raise AssertionError("should not download for an invalid URL")

    monkeypatch.setattr(
        pipeline,
        "download_repo_zip",
        must_not_be_called,
    )

    with pytest.raises(InvalidGitHubURL):
        pipeline.load_repository(
            "https://gitlab.com/pallets/flask",
            tmp_path,
        )