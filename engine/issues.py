
"""Find beginner-friendly contribution issues on GitHub."""

from typing import Any

import httpx

from engine.fetch import GitHubAPIError, _github_headers


GITHUB_API = "https://api.github.com"

BEGINNER_LABELS = {
    "good first issue",
    "good-first-issue",
    "first timers only",
    "beginner",
    "easy",
    "help wanted",
}


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

    if response.status_code in (403, 429):
        raise GitHubAPIError(
            "GitHub rate limit or access restriction reached"
        )

    if response.status_code == 404:
        raise GitHubAPIError(
            f"Repository {owner}/{repo} was not found or is not public"
        )

    if response.status_code != 200:
        raise GitHubAPIError(
            f"GitHub API returned HTTP {response.status_code}"
        )

    try:
        issues = response.json()
    except ValueError as exc:
        raise GitHubAPIError("GitHub returned invalid JSON") from exc

    if not isinstance(issues, list):
        raise GitHubAPIError("Unexpected GitHub API response")

    results = []

    for issue in issues:
        # GitHub's Issues API includes pull requests.
        if "pull_request" in issue:
            continue

        labels = [
            label.get("name", "")
            for label in issue.get("labels", [])
            if isinstance(label, dict)
        ]

        beginner_labelled = any(
            label.strip().lower() in BEGINNER_LABELS
            for label in labels
        )

        title = issue.get("title", "")
        body = issue.get("body") or ""
        searchable_text = f"{title} {body}".lower()

        starter_keywords = (
            "good first issue",
            "beginner",
            "first-time contributor",
            "first time contributor",
            "easy fix",
            "documentation",
            "typo",
        )

        starter_wording = any(
            keyword in searchable_text
            for keyword in starter_keywords
        )

        if not beginner_labelled and not starter_wording:
            continue

        results.append(
            {
                "number": issue.get("number"),
                "title": title,
                "url": issue.get("html_url", ""),
                "labels": labels,
                "reason": (
                    "Has a beginner-friendly label"
                    if beginner_labelled
                    else "Description suggests a starter contribution"
                ),
            }
        )

        if len(results) >= limit:
            break

    return results
