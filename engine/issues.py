
"""Find beginner-friendly contribution issues on GitHub."""

from typing import Any

import httpx

from engine.fetch import (
    GitHubAPIError,
    RepositoryNotFound,
    _github_headers,
    _raise_for_github_status,
    _response_json,
)


GITHUB_API = "https://api.github.com"

STRONG_BEGINNER_LABELS = {
    "good first issue",
    "good-first-issue",
    "first timers only",
    "beginner",
    "easy",
}

HELP_WANTED_LABELS = {"help wanted"}

DIFFICULTY_LABELS = {
    "hard",
    "advanced",
    "difficult",
}

TITLE_BEGINNER_KEYWORDS = (
    "good first issue",
    "beginner",
    "first-time contributor",
    "first time contributor",
    "easy fix",
    "starter issue",
    "new contributor",
)


def _issue_field_error(index: int, field: str, requirement: str) -> GitHubAPIError:
    return GitHubAPIError(
        f"Malformed GitHub issue response at index {index}: "
        f"'{field}' {requirement}"
    )


def _required_issue_number(issue: dict, index: int) -> int:
    number = issue.get("number")

    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise _issue_field_error(index, "number", "must be a positive integer")

    return number


def _required_issue_string(issue: dict, index: int, field: str) -> str:
    value = issue.get(field)

    if not isinstance(value, str) or not value:
        raise _issue_field_error(index, field, "must be a non-empty string")

    return value


def _issue_labels(issue: dict, index: int) -> list[str]:
    raw_labels = issue.get("labels")

    if raw_labels is None:
        return []

    if not isinstance(raw_labels, list):
        raise _issue_field_error(index, "labels", "must be a list")

    labels = []

    for label in raw_labels:
        if not isinstance(label, dict):
            raise _issue_field_error(index, "labels", "must contain objects")

        name = label.get("name")

        if not isinstance(name, str):
            raise _issue_field_error(index, "labels.name", "must be a string")

        labels.append(name)

    return labels


def _issue_body(issue: dict, index: int) -> str:
    body = issue.get("body")

    if body is None:
        return ""

    if not isinstance(body, str):
        raise _issue_field_error(index, "body", "must be a string or null")

    return body


def find_first_contribution_issues(
    owner: str,
    repo: str,
    limit: int = 10,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Return open issues suitable for a first contribution."""
    if limit <= 0:
        return []

    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"

    try:
        response = httpx.get(
            url,
            headers=_github_headers(),
            params={
                "state": "open",
                "per_page": min(limit * 3, 100),
                "sort": "created",
                "direction": "desc",
            },
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise GitHubAPIError(
            f"Could not fetch contribution issues: {exc}"
        ) from exc

    action = f"fetching issues for {owner}/{repo}"

    _raise_for_github_status(
        response,
        action=action,
        not_found_error=RepositoryNotFound,
        not_found_message=(
            f"Repository {owner}/{repo} was not found or is not public"
        ),
    )

    issues = _response_json(response, action=action)

    if not isinstance(issues, list):
        raise GitHubAPIError(
            f"Unexpected GitHub issues response for {owner}/{repo}"
        )

    results = []

    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            raise GitHubAPIError(
                f"Malformed GitHub issue response at index {index}: "
                "expected an object"
            )

        # GitHub's Issues API includes pull requests.
        if "pull_request" in issue:
            continue

        number = _required_issue_number(issue, index)
        title = _required_issue_string(issue, index, "title")
        url = _required_issue_string(issue, index, "html_url")
        labels = _issue_labels(issue, index)
        body = _issue_body(issue, index)

        normalized_labels = {
            label.strip().lower()
            for label in labels
        }

        strongly_beginner_labelled = bool(
            normalized_labels & STRONG_BEGINNER_LABELS
        )
        help_wanted_labelled = bool(
            normalized_labels & HELP_WANTED_LABELS
        )
        has_difficulty_label = bool(
            normalized_labels & DIFFICULTY_LABELS
        )

        if has_difficulty_label and not strongly_beginner_labelled:
            continue

        beginner_labelled = (
            strongly_beginner_labelled or help_wanted_labelled
        )

        starter_wording = any(
            keyword in title.lower()
            for keyword in TITLE_BEGINNER_KEYWORDS
        )

        if not beginner_labelled and not starter_wording:
            continue

        results.append(
            {
                "number": number,
                "title": title,
                "body": body,
                "url": url,
                "labels": labels,
                "reason": (
                    "Has a beginner-friendly label"
                    if beginner_labelled
                    else "Title suggests a starter contribution"
                ),
            }
        )

        if len(results) >= limit:
            break

    return results
