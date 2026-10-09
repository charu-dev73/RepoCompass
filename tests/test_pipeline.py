import zipfile
from pathlib import Path

import pytest

from engine import pipeline
from engine.fetch import InvalidGitHubURL


def make_repo_zip(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "pallets-flask-abc123/app.py",
            '"""Application entry."""\n\ndef main():\n    pass\n\n'
            'if __name__ == "__main__":\n    main()\n',
        )
        archive.writestr(
            "pallets-flask-abc123/pkg/util.py",
            "def helper():\n    pass\n",
        )
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

    assert [info.path for info in snapshot.files] == [
        Path("app.py"),
        Path("pkg/util.py"),
    ]

    app_info, util_info = snapshot.files

    assert app_info.docstring == "Application entry."
    assert app_info.functions == ["main"]
    assert app_info.has_main_guard is True
    assert app_info.parse_error is None

    assert util_info.functions == ["helper"]
    assert util_info.has_main_guard is False
    assert util_info.parse_error is None


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
