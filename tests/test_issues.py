
import httpx
import pytest

from engine.fetch import GitHubAPIError
from engine.issues import find_first_contribution_issues


def mock_response(payload, status_code=200):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://api.github.com/test"),
    )


def test_returns_beginner_friendly_issues(monkeypatch):
    def fake_get(url, **kwargs):
        return mock_response([
            {
                "number": 12,
                "title": "Fix documentation typo",
                "html_url": "https://github.com/example/repo/issues/12",
                "labels": [{"name": "good first issue"}],
            },
            {
                "number": 13,
                "title": "Add feature",
                "html_url": "https://github.com/example/repo/issues/13",
                "labels": [{"name": "bug"}],
            },
            {
                "number": 14,
                "title": "Improve tests",
                "html_url": "https://github.com/example/repo/issues/14",
                "labels": [{"name": "HELP WANTED"}],
            },
        ])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = find_first_contribution_issues("example", "repo")

    assert [issue["number"] for issue in result] == [12, 14]


def test_excludes_pull_requests(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            {
                "number": 1,
                "title": "A pull request",
                "html_url": "https://github.com/example/repo/pull/1",
                "labels": [{"name": "good first issue"}],
                "pull_request": {"url": "https://api.github.com/test"},
            },
        ]),
    )

    assert find_first_contribution_issues("example", "repo") == []


def test_returns_empty_for_no_matching_issues(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([]),
    )

    assert find_first_contribution_issues("example", "repo") == []


def test_non_positive_limit_returns_empty():
    assert find_first_contribution_issues("example", "repo", limit=0) == []


@pytest.mark.parametrize("status_code", [403, 429, 404, 500])
def test_handles_github_api_errors(monkeypatch, status_code):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response({}, status_code),
    )

    with pytest.raises(GitHubAPIError):
        find_first_contribution_issues("example", "repo")
