import zipfile
from pathlib import Path

import pytest

from engine import pipeline
from engine.fetch import (
    GitHubAPIError,
    InvalidGitHubURL,
    RepositoryNotFound,
)


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


def make_issue_repo_zip(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "example-repo-abc123/src/auth.py",
            'def refresh_token():\n'
            '    """Refresh an authentication token."""\n'
            "    pass\n",
        )
        archive.writestr(
            "example-repo-abc123/src/database.py",
            "def connect():\n    pass\n",
        )
        archive.writestr(
            "example-repo-abc123/docs/auth.md",
            "# Authentication\n\n"
            "Token refresh failures can happen when authentication "
            "credentials expire.\n",
        )
        archive.writestr(
            "example-repo-abc123/docs/install.md",
            "# Installation\n\nInstall the package with pip.\n",
        )
        archive.writestr(
            "example-repo-abc123/README.md",
            "# Example\n",
        )


def contribution_issue():
    return {
        "number": 42,
        "title": "Token refresh fails",
        "body": (
            "The `refresh_token` function in `src/auth.py` fails. "
            "Please update the authentication docs."
        ),
        "url": "https://github.com/example/repo/issues/42",
        "labels": ["good first issue"],
    }


def test_load_repository_maps_issue_to_files_and_docs(
    monkeypatch,
    tmp_path,
):
    def fake_download(owner, repo, dest_dir):
        zip_path = dest_dir / "repo.zip"
        make_issue_repo_zip(zip_path)
        return zip_path

    issue = contribution_issue()

    monkeypatch.setattr(pipeline, "download_repo_zip", fake_download)
    monkeypatch.setattr(
        pipeline,
        "find_first_contribution_issues",
        lambda owner, repo: [issue],
    )

    snapshot = pipeline.load_repository(
        "https://github.com/example/repo",
        tmp_path,
        fetch_issues=True,
    )

    assert snapshot.contribution_issues == [issue]

    file_matches = snapshot.issue_file_matches[42]
    assert file_matches[0]["path"] == "src/auth.py"
    assert file_matches[0]["score"] == 198
    assert "Issue explicitly mentions this file" in file_matches[0]["reasons"]
    assert (
        "Defines the mentioned identifier `refresh_token`"
        in file_matches[0]["reasons"]
    )

    doc_matches = snapshot.issue_doc_matches[42]
    assert doc_matches[0]["path"] == Path("docs/auth.md")
    assert doc_matches[0]["score"] == 42
    assert (
        "Issue title term 'refresh' appears in the document."
        in doc_matches[0]["reasons"]
    )
    assert (
        "Related title phrase 'token refresh' appears in a paragraph."
        in doc_matches[0]["reasons"]
    )


def test_missing_optional_issue_fields_do_not_abort_analysis(
    monkeypatch,
    tmp_path,
):
    def fake_download(owner, repo, dest_dir):
        zip_path = dest_dir / "repo.zip"
        make_issue_repo_zip(zip_path)
        return zip_path

    issue = {
        "number": 7,
        "title": "Authentication token refresh is confusing",
        "url": "https://github.com/example/repo/issues/7",
    }

    monkeypatch.setattr(pipeline, "download_repo_zip", fake_download)
    monkeypatch.setattr(
        pipeline,
        "find_first_contribution_issues",
        lambda owner, repo: [issue],
    )

    snapshot = pipeline.load_repository(
        "https://github.com/example/repo",
        tmp_path,
        fetch_issues=True,
    )

    assert snapshot.contribution_issues == [issue]
    assert snapshot.discovery.python_files == [
        Path("src/auth.py"),
        Path("src/database.py"),
    ]
    assert snapshot.doc_discovery.doc_files == [
        Path("README.md"),
        Path("docs/auth.md"),
        Path("docs/install.md"),
    ]
    assert 7 in snapshot.issue_file_matches
    assert 7 in snapshot.issue_doc_matches


def test_malformed_optional_issue_data_warns_without_aborting(
    monkeypatch,
    tmp_path,
    capsys,
):
    def fake_download(owner, repo, dest_dir):
        zip_path = dest_dir / "repo.zip"
        make_issue_repo_zip(zip_path)
        return zip_path

    def fake_issues(owner, repo):
        raise GitHubAPIError(
            "Malformed GitHub issue response at index 0: "
            "'labels' must be a list"
        )

    monkeypatch.setattr(pipeline, "download_repo_zip", fake_download)
    monkeypatch.setattr(
        pipeline,
        "find_first_contribution_issues",
        fake_issues,
    )

    snapshot = pipeline.load_repository(
        "https://github.com/example/repo",
        tmp_path,
        fetch_issues=True,
    )

    assert snapshot.contribution_issues == []
    assert snapshot.issue_file_matches == {}
    assert snapshot.issue_doc_matches == {}
    assert snapshot.discovery.python_files == [
        Path("src/auth.py"),
        Path("src/database.py"),
    ]

    captured = capsys.readouterr()

    assert "Warning: could not fetch contribution issues" in captured.out
    assert "'labels' must be a list" in captured.out


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


def test_issue_not_found_warns_without_aborting(
    monkeypatch,
    tmp_path,
    capsys,
):
    def fake_download(owner, repo, dest_dir):
        zip_path = dest_dir / "repo.zip"
        make_repo_zip(zip_path)
        return zip_path

    def fake_issues(owner, repo):
        raise RepositoryNotFound(
            f"{owner}/{repo} not found, or it is not public"
        )

    monkeypatch.setattr(pipeline, "download_repo_zip", fake_download)
    monkeypatch.setattr(
        pipeline,
        "find_first_contribution_issues",
        fake_issues,
    )

    snapshot = pipeline.load_repository(
        "https://github.com/pallets/flask",
        tmp_path,
        fetch_issues=True,
    )

    assert snapshot.contribution_issues == []
    assert snapshot.discovery.python_files == [
        Path("app.py"),
        Path("pkg/util.py"),
    ]

    captured = capsys.readouterr()

    assert "Warning: could not fetch contribution issues" in captured.out
    assert "not found" in captured.out


def test_load_repository_resolves_symlinked_workdir(
    monkeypatch,
    tmp_path,
):
    real_workdir = tmp_path / "real"
    real_workdir.mkdir()
    linked_workdir = tmp_path / "linked"
    linked_workdir.symlink_to(
        real_workdir,
        target_is_directory=True,
    )

    def fake_download(owner, repo, dest_dir):
        assert dest_dir == real_workdir
        zip_path = dest_dir / "repo.zip"
        make_repo_zip(zip_path)
        return zip_path

    monkeypatch.setattr(pipeline, "download_repo_zip", fake_download)

    snapshot = pipeline.load_repository(
        "https://github.com/pallets/flask",
        linked_workdir,
    )

    assert (
        snapshot.root
        == real_workdir / "extracted" / "pallets-flask-abc123"
    )
    assert (snapshot.root / "app.py").is_file()


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
