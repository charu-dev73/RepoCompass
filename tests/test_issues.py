
import httpx
import pytest

from engine.fetch import GitHubAPIError, RepositoryNotFound
from engine.issues import find_first_contribution_issues


def mock_response(payload, status_code=200):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://api.github.com/test"),
    )


def valid_issue():
    return {
        "number": 12,
        "title": "Fix documentation typo",
        "html_url": "https://github.com/example/repo/issues/12",
        "labels": [{"name": "good first issue"}],
    }


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


def test_unlabeled_body_documentation_mention_is_excluded(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            {
                "number": 210,
                "title": "Flake8 configuration should not use select",
                "html_url": (
                    "https://github.com/pypa/sampleproject/issues/210"
                ),
                "labels": [],
                "body": (
                    "The flake8 documentation states that select is "
                    "usually unnecessary."
                ),
            },
        ]),
    )

    assert find_first_contribution_issues("example", "repo") == []


@pytest.mark.parametrize(
    "difficulty_label",
    ["Hard", "Advanced", "Difficult"],
)
def test_help_wanted_with_difficulty_label_is_excluded(
    monkeypatch,
    difficulty_label,
):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            {
                "number": 12,
                "title": "Improve test coverage",
                "html_url": "https://github.com/example/repo/issues/12",
                "labels": [
                    {"name": "help wanted"},
                    {"name": difficulty_label},
                ],
            },
        ]),
    )

    assert find_first_contribution_issues("example", "repo") == []


def test_explicit_beginner_label_is_retained(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            {
                "number": 12,
                "title": "Add a feature",
                "html_url": "https://github.com/example/repo/issues/12",
                "labels": [{"name": "good first issue"}],
            },
        ]),
    )

    result = find_first_contribution_issues("example", "repo")

    assert [issue["number"] for issue in result] == [12]


def test_beginner_title_without_label_is_retained(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            {
                "number": 12,
                "title": "Good first issue: improve an error message",
                "html_url": "https://github.com/example/repo/issues/12",
                "labels": [],
            },
        ]),
    )

    result = find_first_contribution_issues("example", "repo")

    assert [issue["number"] for issue in result] == [12]


def test_ordinary_documentation_mention_does_not_qualify(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            {
                "number": 12,
                "title": "Fix typo in documentation",
                "html_url": "https://github.com/example/repo/issues/12",
                "labels": [],
                "body": (
                    "Update the documentation and setup examples."
                ),
            },
        ]),
    )

    assert find_first_contribution_issues("example", "repo") == []


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


@pytest.mark.parametrize(
    "status_code, error",
    [
        (403, GitHubAPIError),
        (429, GitHubAPIError),
        (404, RepositoryNotFound),
        (500, GitHubAPIError),
    ],
)
def test_handles_github_api_errors(monkeypatch, status_code, error):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response({}, status_code),
    )

    with pytest.raises(error):
        find_first_contribution_issues("example", "repo")


def test_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: httpx.Response(
            200,
            content=b"not json",
            request=httpx.Request("GET", "https://api.github.com/test"),
        ),
    )

    with pytest.raises(GitHubAPIError):
        find_first_contribution_issues("example", "repo")


def test_rejects_non_list_json(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response({"not": "a list"}),
    )

    with pytest.raises(GitHubAPIError):
        find_first_contribution_issues("example", "repo")


def test_rejects_non_object_issue(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response(["not an object"]),
    )

    with pytest.raises(GitHubAPIError):
        find_first_contribution_issues("example", "repo")


@pytest.mark.parametrize(
    "missing_field",
    ["number", "title", "html_url"],
)
def test_rejects_missing_issue_fields(monkeypatch, missing_field):
    issue = valid_issue()
    issue.pop(missing_field)

    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([issue]),
    )

    with pytest.raises(GitHubAPIError):
        find_first_contribution_issues("example", "repo")


@pytest.mark.parametrize(
    "field, value",
    [
        ("number", "12"),
        ("number", True),
        ("number", 0),
        ("number", -1),
        ("title", None),
        ("title", 12),
        ("title", ""),
        ("html_url", None),
        ("html_url", 12),
        ("html_url", ""),
        ("labels", "good first issue"),
        ("labels", [{"name": 12}]),
        ("labels", ["good first issue"]),
        ("body", 12),
    ],
)
def test_rejects_invalid_issue_field_types(monkeypatch, field, value):
    issue = valid_issue()
    issue[field] = value

    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([issue]),
    )

    with pytest.raises(GitHubAPIError):
        find_first_contribution_issues("example", "repo")


def test_accepts_missing_optional_issue_fields(monkeypatch):
    issue = valid_issue()
    issue["title"] = "Good first issue: fix documentation typo"
    issue.pop("labels")

    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([issue]),
    )

    result = find_first_contribution_issues("example", "repo")

    assert result[0]["labels"] == []
    assert result[0]["body"] == ""


def test_skips_pull_requests_before_validating_title(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            {
                "pull_request": {"url": "https://api.github.com/test"},
            },
        ]),
    )

    assert find_first_contribution_issues("example", "repo") == []
