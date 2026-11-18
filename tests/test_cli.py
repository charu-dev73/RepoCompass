from pathlib import Path

import zipfile

import cli
from engine import pipeline
from engine.issues import IssueDiscoveryResult


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


def test_successful_analysis_shows_issue_matches(monkeypatch, capsys):
    def fake_download(owner, repo, dest_dir):
        zip_path = dest_dir / "repo.zip"
        make_issue_repo_zip(zip_path)
        return zip_path

    monkeypatch.setattr(pipeline, "download_repo_zip", fake_download)
    monkeypatch.setattr(
        pipeline,
        "discover_contribution_issues",
        lambda owner, repo: IssueDiscoveryResult(
            issues=[contribution_issue()]
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["cli.py", "https://github.com/example/repo"],
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert "Analysed: example/repo" in output
    assert "Python files discovered: 2" in output
    assert "Documentation files discovered: 3" in output
    assert "\nPython files:\n  src/auth.py\n  src/database.py" in output
    assert "\nBeginner-friendly contribution issues:" in output
    assert "\n  #42: Token refresh fails" in output
    assert "  URL: https://github.com/example/repo/issues/42" in output
    assert "  Labels: good first issue" in output
    assert "  Relevant Python files:" in output
    assert "    - src/auth.py (score: 198)" in output
    assert "      Why: Issue explicitly mentions this file" in output
    assert (
        "      Why: Defines the mentioned identifier `refresh_token`"
        in output
    )
    assert "  Relevant documentation files:" in output
    assert "    - docs/auth.md (score: 42)" in output
    assert (
        "      Why: Issue title term 'refresh' appears in the document."
        in output
    )
    assert (
        "      Why: Related title phrase 'token refresh' appears "
        "in a paragraph."
        in output
    )


def test_no_arguments_prints_usage_and_returns_2(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["cli.py"])

    assert cli.main() == 2
    assert "Usage" in capsys.readouterr().out


def test_invalid_url_prints_error_and_returns_1(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["cli.py", "https://gitlab.com/pallets/flask"],
    )

    assert cli.main() == 1
    assert "Not a github.com URL" in capsys.readouterr().err


def _issue_snapshot(issue_discovery):
    from engine.discover import DiscoveryResult, DocDiscoveryResult
    from engine.graph import DependencyGraph

    return pipeline.RepoSnapshot(
        owner="example",
        repo="repo",
        root=Path("."),
        discovery=DiscoveryResult(),
        files=[],
        doc_discovery=DocDiscoveryResult(),
        graph=DependencyGraph(),
        contribution_issues=[],
        issue_file_matches={},
        issue_doc_matches={},
        issue_discovery=issue_discovery,
    )


def test_complete_with_zero_issues_reports_no_matches(monkeypatch, capsys):
    snapshot = _issue_snapshot(
        {
            "status": "complete",
            "complete": True,
            "issues_found": 0,
            "scanned_items": 12,
            "pages_fetched": 12,
            "warnings": [],
            "error": None,
        }
    )
    monkeypatch.setattr(
        cli,
        "load_repository",
        lambda url, workdir, fetch_issues=False: snapshot,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["cli.py", "https://github.com/example/repo"],
    )

    assert cli.main() == 0
    output = capsys.readouterr().out

    assert "No matching open issues found." in output
    assert "Issue scan incomplete" not in output
    assert "Issue discovery failed" not in output


def test_budget_exhausted_with_zero_issues_is_not_fatal(monkeypatch, capsys):
    snapshot = _issue_snapshot(
        {
            "status": "budget_exhausted",
            "complete": False,
            "issues_found": 0,
            "scanned_items": 300,
            "pages_fetched": 8,
            "warnings": ["scan budget exhausted"],
            "error": None,
        }
    )
    monkeypatch.setattr(
        cli,
        "load_repository",
        lambda url, workdir, fetch_issues=False: snapshot,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["cli.py", "https://github.com/example/repo"],
    )

    assert cli.main() == 0
    output = capsys.readouterr().out

    assert "Issue scan incomplete (scan budget exhausted)." in output
    assert "Issues found: 0" in output
    assert "Items scanned: 300" in output
    assert "No matching open issues found." not in output
    assert "Issue discovery failed" not in output


def test_failed_issue_discovery_with_zero_issues_is_nonzero(
    monkeypatch,
    capsys,
):
    snapshot = _issue_snapshot(
        {
            "status": "failed",
            "complete": False,
            "issues_found": 0,
            "scanned_items": 5,
            "pages_fetched": 1,
            "warnings": ["could not fetch contribution issues: HTTP 500"],
            "error": {"type": "GitHubAPIError", "message": "HTTP 500"},
        }
    )
    monkeypatch.setattr(
        cli,
        "load_repository",
        lambda url, workdir, fetch_issues=False: snapshot,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["cli.py", "https://github.com/example/repo"],
    )

    assert cli.main() == 1
    output = capsys.readouterr().out

    assert "Issue discovery failed." in output
    assert "Issues found before failure: 0" in output
    assert "Items scanned: 5" in output
    assert "No matching open issues found." not in output


def test_fetch_issues_disabled_preserves_normal_output(monkeypatch, capsys):
    snapshot = _issue_snapshot(None)
    monkeypatch.setattr(
        cli,
        "load_repository",
        lambda url, workdir, fetch_issues=False: snapshot,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["cli.py", "https://github.com/example/repo"],
    )

    assert cli.main() == 0
    output = capsys.readouterr().out

    assert "No matching open issues found." in output
    assert "Issue scan incomplete" not in output
    assert "Issue discovery failed" not in output