
import httpx
import pytest

from engine.fetch import GitHubAPIError, RepositoryNotFound
from engine.issues import (
    CANDIDATE_LABELS,
    IssueDiscoveryStatus,
    discover_contribution_issues,
    find_first_contribution_issues,
)


def mock_response(payload, status_code=200, headers=None):
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=httpx.Request("GET", "https://api.github.com/test"),
    )


def issue_payload(number, *, labels=None, title="Eligible issue"):
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/example/repo/issues/{number}",
        "labels": [
            {"name": label}
            for label in (labels or ["good first issue"])
        ],
    }


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


def test_pagination_finds_eligible_issue_on_page_two(monkeypatch):
    calls = []
    next_page = "https://api.github.com/repos/example/repo/issues?page=2"

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))

        if len(calls) == 1:
            return mock_response(
                [{"pull_request": {"url": "https://api.github.com/test"}}],
                headers={"Link": f'<{next_page}>; rel="next"'},
            )

        return mock_response([issue_payload(12)])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo", limit=1)

    assert result.status is IssueDiscoveryStatus.COMPLETE
    assert result.complete is True
    assert [issue["number"] for issue in result.issues] == [12]
    assert result.pages_fetched == 2
    assert result.scanned_items == 2
    assert result.warnings == []
    assert calls[0][1]["params"]["labels"] == "good first issue"
    assert calls[0][1]["params"]["per_page"] == 25
    assert calls[1][0] == next_page
    assert result.as_dict()["status"] == "complete"
    assert result.as_dict()["issues_found"] == 1


def test_pr_heavy_pages_do_not_prevent_eligible_issue_discovery(monkeypatch):
    calls = []
    next_page = "https://api.github.com/repos/example/repo/issues?page=2"

    def fake_get(url, **kwargs):
        calls.append(url)

        if len(calls) == 1:
            return mock_response(
                [
                    {"pull_request": {"url": f"https://api.github.com/test/{n}"}}
                    for n in range(5)
                ],
                headers={"Link": f'<{next_page}>; rel="next"'},
            )

        return mock_response([issue_payload(12)])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo", limit=1)

    assert [issue["number"] for issue in result.issues] == [12]
    assert result.status is IssueDiscoveryStatus.COMPLETE
    assert result.scanned_items == 6
    assert result.pages_fetched == 2


def test_pagination_stops_when_result_limit_is_reached(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return mock_response([
            issue_payload(12),
            issue_payload(13),
            issue_payload(14),
        ])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo", limit=2)

    assert [issue["number"] for issue in result.issues] == [12, 13]
    assert result.status is IssueDiscoveryStatus.COMPLETE
    assert result.scanned_items == 2
    assert len(calls) == 1


def test_scan_budget_returns_incomplete_partial_result(monkeypatch):
    calls = []
    next_page = "https://api.github.com/repos/example/repo/issues?page=2"

    def fake_get(url, **kwargs):
        calls.append(url)
        return mock_response(
            [
                issue_payload(12),
                {"pull_request": {"url": "https://api.github.com/test"}},
            ],
            headers={"Link": f'<{next_page}>; rel="next"'},
        )

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues(
        "example",
        "repo",
        max_scan_items=2,
    )

    assert result.status is IssueDiscoveryStatus.BUDGET_EXHAUSTED
    assert result.complete is False
    assert [issue["number"] for issue in result.issues] == [12]
    assert result.scanned_items == 2
    assert result.pages_fetched == 2
    assert result.warnings
    assert "scan budget" in result.warnings[0]
    assert result.as_dict()["complete"] is False
    assert len(calls) == 2


def test_completed_scan_with_zero_results_is_complete(monkeypatch):
    def fake_get(url, **kwargs):
        params = kwargs.get("params") or {}

        if "labels" in params:
            return mock_response([])

        return mock_response([
            {
                "number": 1,
                "title": "An ordinary bug",
                "html_url": "https://github.com/example/repo/issues/1",
                "labels": [{"name": "bug"}],
            },
            {"pull_request": {"url": "https://api.github.com/test"}},
        ])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo")

    assert result.status is IssueDiscoveryStatus.COMPLETE
    assert result.complete is True
    assert result.issues == []
    assert result.scanned_items == 2
    assert result.pages_fetched == len(CANDIDATE_LABELS) + 1
    assert result.warnings == []


def test_api_failure_returns_incomplete_result(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response({}, status_code=500),
    )

    result = discover_contribution_issues("example", "repo")

    assert result.status is IssueDiscoveryStatus.FAILED
    assert result.complete is False
    assert result.issues == []
    assert result.warnings
    assert "could not fetch contribution issues" in result.warnings[0]
    assert result.as_dict()["error"]["status_code"] == 500
    assert "HTTP 500" in result.as_dict()["error"]["message"]


def test_rate_limit_details_are_reported(monkeypatch):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response(
            {},
            status_code=403,
            headers={
                "Retry-After": "60",
                "X-RateLimit-Reset": "1700000000",
            },
        ),
    )

    result = discover_contribution_issues("example", "repo")

    assert result.status is IssueDiscoveryStatus.FAILED
    assert result.as_dict()["error"] == {
        "type": "GitHubAPIError",
        "message": (
            "GitHub rate limit or access restriction reached while "
            "fetching issues for example/repo "
            "(Retry-After: 60; X-RateLimit-Reset: 1700000000)"
        ),
        "status_code": 403,
        "retry_after": "60",
        "rate_limit_reset": "1700000000",
    }


@pytest.mark.parametrize(
    "label",
    [
        "help-wanted",
        "help_wanted",
        "Help Wanted",
        "HELP---WANTED",
    ],
)
def test_help_wanted_label_variants_normalize(monkeypatch, label):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            issue_payload(12, labels=[label]),
        ]),
    )

    result = discover_contribution_issues("example", "repo")

    assert [issue["number"] for issue in result.issues] == [12]


@pytest.mark.parametrize(
    "label",
    [
        "good-first-issue",
        "GOOD_FIRST_ISSUE",
        " good first issue ",
    ],
)
def test_strong_beginner_label_variants_normalize(monkeypatch, label):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            issue_payload(12, labels=[label]),
        ]),
    )

    result = discover_contribution_issues("example", "repo")

    assert [issue["number"] for issue in result.issues] == [12]


@pytest.mark.parametrize(
    "difficulty_label",
    ["Hard", "advanced", "DIFFICULT"],
)
def test_normalized_help_wanted_with_difficulty_is_excluded(
    monkeypatch,
    difficulty_label,
):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            issue_payload(
                12,
                labels=["help-wanted", difficulty_label],
            ),
        ]),
    )

    result = discover_contribution_issues("example", "repo")

    assert result.issues == []
    assert result.status is IssueDiscoveryStatus.COMPLETE


def test_candidate_retrieval_requests_labels_and_fallback(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        params = kwargs.get("params") or {}
        calls.append(params.get("labels"))
        return mock_response([])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo")

    assert calls == [*CANDIDATE_LABELS, None]
    assert result.status is IssueDiscoveryStatus.COMPLETE
    assert result.scanned_items == 0
    assert result.pages_fetched == len(CANDIDATE_LABELS) + 1
    assert "good-first-issue" in CANDIDATE_LABELS
    assert "good_first_issue" in CANDIDATE_LABELS
    assert "help-wanted" in CANDIDATE_LABELS
    assert "help_wanted" in CANDIDATE_LABELS


def test_cross_host_pagination_is_rejected_without_request(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "audit-token")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("headers")))
        return mock_response(
            [],
            headers={
                "Link": '<https://evil.example/steal>; rel="next"',
            },
        )

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo")

    assert result.status is IssueDiscoveryStatus.FAILED
    assert result.complete is False
    assert len(calls) == 1
    assert calls[0][0] == (
        "https://api.github.com/repos/example/repo/issues"
    )
    assert calls[0][1]["Authorization"] == "Bearer audit-token"
    assert "untrusted" in result.warnings[0]
    assert result.as_dict()["error"]["type"] == "GitHubAPIError"


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://api.github.com/repos/example/repo/issues?page=2",
        "https://api.github.com:444/repos/example/repo/issues?page=2",
        "https://api.github.com@evil.example/issues?page=2",
        "https://evil.example/repos/example/repo/issues?page=2",
    ],
)
def test_unsafe_pagination_urls_are_rejected(monkeypatch, unsafe_url):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return mock_response(
            [],
            headers={"Link": f'<{unsafe_url}>; rel="next"'},
        )

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo")

    assert result.status is IssueDiscoveryStatus.FAILED
    assert len(calls) == 1
    assert "untrusted" in result.warnings[0]


@pytest.mark.parametrize(
    "link_header",
    [
        '<>; rel="next"',
        '<not a url>; rel="next"',
    ],
)
def test_unusable_next_relation_returns_failed(monkeypatch, link_header):
    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response(
            [],
            headers={"Link": link_header},
        ),
    )

    result = discover_contribution_issues("example", "repo")

    assert result.status is IssueDiscoveryStatus.FAILED
    assert result.complete is False
    assert result.warnings
    assert (
        "next" in result.warnings[0]
        or "pagination URL" in result.warnings[0]
    )
    assert result.as_dict()["error"] is not None


def test_invalid_url_exception_returns_failed(monkeypatch):
    def fake_get(url, **kwargs):
        raise httpx.InvalidURL("invalid URL")

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo")

    assert result.status is IssueDiscoveryStatus.FAILED
    assert result.complete is False
    assert "Could not fetch contribution issues" in result.warnings[0]
    assert result.as_dict()["error"]["type"] == "GitHubAPIError"


def test_partial_results_survive_page_two_failure(monkeypatch):
    calls = []
    next_page = "https://api.github.com/repos/example/repo/issues?page=2"

    def fake_get(url, **kwargs):
        calls.append(url)

        if len(calls) == 1:
            return mock_response(
                [issue_payload(12)],
                headers={"Link": f'<{next_page}>; rel="next"'},
            )

        return mock_response({}, status_code=500)

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo")

    assert result.status is IssueDiscoveryStatus.FAILED
    assert [issue["number"] for issue in result.issues] == [12]
    assert result.scanned_items == 1
    assert result.pages_fetched == 1
    assert "could not fetch contribution issues" in result.warnings[0]
    assert result.as_dict()["error"]["status_code"] == 500


def test_label_filtered_retrieval_finds_issue_before_mixed_fallback(
    monkeypatch,
):
    calls = []

    def fake_get(url, **kwargs):
        params = kwargs.get("params") or {}
        calls.append(params.get("labels"))

        if params.get("labels") == "good first issue":
            return mock_response([issue_payload(500)])

        return mock_response([
            {"pull_request": {"url": "https://api.github.com/test"}}
        ])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo", limit=1)

    assert [issue["number"] for issue in result.issues] == [500]
    assert result.status is IssueDiscoveryStatus.COMPLETE
    assert result.pages_fetched == 1
    assert calls == ["good first issue"]


def test_duplicate_issues_across_sources_are_removed(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return mock_response([issue_payload(12)])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo")

    assert [issue["number"] for issue in result.issues] == [12]
    assert result.scanned_items == len(CANDIDATE_LABELS) + 1
    assert result.pages_fetched == len(CANDIDATE_LABELS) + 1
    assert len(calls) == len(CANDIDATE_LABELS) + 1


def test_hyphenated_and_underscored_label_variants_are_queried(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        params = kwargs.get("params") or {}
        labels = params.get("labels")
        calls.append(labels)

        if labels == "good-first-issue":
            return mock_response(
                [issue_payload(101, labels=["good-first-issue"])]
            )

        if labels == "help_wanted":
            return mock_response(
                [issue_payload(202, labels=["help_wanted"])]
            )

        return mock_response([])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues("example", "repo")

    assert "good-first-issue" in calls
    assert "good_first_issue" in calls
    assert "help-wanted" in calls
    assert "help_wanted" in calls
    assert [issue["number"] for issue in result.issues] == [101, 202]
    assert result.status is IssueDiscoveryStatus.COMPLETE
    assert result.pages_fetched == len(CANDIDATE_LABELS) + 1
    assert result.as_dict()["complete"] is True


def test_exact_budget_on_final_page_is_complete(monkeypatch):
    max_scan_items = len(CANDIDATE_LABELS) + 1

    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response([
            {
                "number": 1,
                "title": "An ordinary bug",
                "html_url": "https://github.com/example/repo/issues/1",
                "labels": [{"name": "bug"}],
            },
        ]),
    )

    result = discover_contribution_issues(
        "example",
        "repo",
        max_scan_items=max_scan_items,
    )

    assert result.status is IssueDiscoveryStatus.COMPLETE
    assert result.complete is True
    assert result.scanned_items == max_scan_items
    assert result.pages_fetched == len(CANDIDATE_LABELS) + 1
    assert result.warnings == []


def test_exact_budget_with_more_pages_is_incomplete(monkeypatch):
    max_scan_items = len(CANDIDATE_LABELS) + 1
    next_page = "https://api.github.com/repos/example/repo/issues?page=2"

    monkeypatch.setattr(
        "engine.issues.httpx.get",
        lambda url, **kwargs: mock_response(
            [issue_payload(12)],
            headers={"Link": f'<{next_page}>; rel="next"'},
        ),
    )

    result = discover_contribution_issues(
        "example",
        "repo",
        max_scan_items=max_scan_items,
    )

    assert result.status is IssueDiscoveryStatus.BUDGET_EXHAUSTED
    assert result.complete is False
    assert result.scanned_items == max_scan_items
    assert result.pages_fetched == len(CANDIDATE_LABELS) + 1
    assert "scan budget" in result.warnings[0]


def test_limit_reached_at_global_budget_with_next_page_is_incomplete(
    monkeypatch,
):
    calls = []
    next_page = "https://api.github.com/repos/example/repo/issues?page=2"

    def fake_get(url, **kwargs):
        calls.append(url)
        return mock_response(
            [issue_payload(12)],
            headers={"Link": f'<{next_page}>; rel="next"'},
        )

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues(
        "example",
        "repo",
        limit=1,
        max_scan_items=1,
    )

    assert result.status is IssueDiscoveryStatus.BUDGET_EXHAUSTED
    assert result.complete is False
    assert [issue["number"] for issue in result.issues] == [12]
    assert result.scanned_items == 1
    assert result.pages_fetched == 1
    assert len(calls) == 1
    assert result.warnings


def test_limit_reached_at_source_quota_with_next_page_is_incomplete(
    monkeypatch,
):
    calls = []
    next_page = "https://api.github.com/repos/example/repo/issues?page=2"

    def fake_get(url, **kwargs):
        params = kwargs.get("params") or {}
        calls.append((params.get("labels"), url))
        if params.get("labels") == "good first issue":
            return mock_response(
                [issue_payload(12)],
                headers={"Link": f'<{next_page}>; rel="next"'},
            )
        return mock_response([])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues(
        "example",
        "repo",
        limit=1,
        max_scan_items=len(CANDIDATE_LABELS),
    )

    assert result.status is IssueDiscoveryStatus.BUDGET_EXHAUSTED
    assert result.complete is False
    assert [issue["number"] for issue in result.issues] == [12]
    assert result.scanned_items == 1
    assert result.pages_fetched == 1
    assert calls == [("good first issue", calls[0][1])]
    assert result.warnings


def test_limit_reached_on_final_page_without_next_page_is_complete(
    monkeypatch,
):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return mock_response([issue_payload(12)])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues(
        "example",
        "repo",
        limit=1,
        max_scan_items=len(CANDIDATE_LABELS),
    )

    assert result.status is IssueDiscoveryStatus.COMPLETE
    assert result.complete is True
    assert [issue["number"] for issue in result.issues] == [12]
    assert result.scanned_items == 1
    assert result.pages_fetched == 1
    assert len(calls) == 1
    assert result.warnings == []


def test_mid_page_truncation_is_incomplete(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)

        if len(calls) == 1:
            return mock_response([
                {
                    "number": number,
                    "title": "An ordinary bug",
                    "html_url": (
                        "https://github.com/example/repo/issues/"
                        f"{number}"
                    ),
                    "labels": [{"name": "bug"}],
                }
                for number in range(1, 4)
            ])

        return mock_response([])

    monkeypatch.setattr("engine.issues.httpx.get", fake_get)

    result = discover_contribution_issues(
        "example",
        "repo",
        max_scan_items=12,
    )

    assert result.status is IssueDiscoveryStatus.BUDGET_EXHAUSTED
    assert result.complete is False
    assert result.scanned_items == 1
    assert result.pages_fetched == len(CANDIDATE_LABELS) + 1
    assert "more candidates were available" in result.warnings[0]
