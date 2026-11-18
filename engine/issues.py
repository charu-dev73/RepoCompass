
"""Find beginner-friendly contribution issues on GitHub."""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from engine.fetch import (
    GitHubAPIError,
    RepositoryNotFound,
    _github_headers,
    _response_json,
)


GITHUB_API = "https://api.github.com"
MAX_ITEMS_PER_PAGE = 100
DEFAULT_MAX_SCAN_ITEMS = 300
CANDIDATE_LABELS = (
    "good first issue",
    "good-first-issue",
    "good_first_issue",
    "beginner",
    "first timers only",
    "first-timers-only",
    "first_timers_only",
    "help wanted",
    "help-wanted",
    "help_wanted",
    "easy",
)


def _normalize_label(label: str) -> str:
    return re.sub(r"[\s_-]+", " ", label.strip().lower()).strip()


STRONG_BEGINNER_LABELS = {
    _normalize_label(label)
    for label in (
        "good first issue",
        "good-first-issue",
        "first timers only",
        "beginner",
        "easy",
    )
}

HELP_WANTED_LABELS = {
    _normalize_label("help wanted"),
}

DIFFICULTY_LABELS = {
    _normalize_label(label)
    for label in (
        "hard",
        "advanced",
        "difficult",
    )
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


class IssueDiscoveryStatus(str, Enum):
    COMPLETE = "complete"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FAILED = "failed"


@dataclass
class IssueDiscoveryResult:
    issues: list[dict[str, Any]] = field(default_factory=list)
    status: IssueDiscoveryStatus = IssueDiscoveryStatus.COMPLETE
    scanned_items: int = 0
    pages_fetched: int = 0
    warnings: list[str] = field(default_factory=list)
    error: Exception | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def complete(self) -> bool:
        return self.status is IssueDiscoveryStatus.COMPLETE

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "complete": self.complete,
            "issues_found": len(self.issues),
            "scanned_items": self.scanned_items,
            "pages_fetched": self.pages_fetched,
            "warnings": list(self.warnings),
            "error": _exception_details(self.error),
        }


@dataclass
class _CandidateScanState:
    issues: list[dict[str, Any]] = field(default_factory=list)
    issue_numbers: set[int] = field(default_factory=set)
    scanned_items: int = 0
    pages_fetched: int = 0
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


def _total_budget_warning(
    scanned_items: int,
    max_scan_items: int,
) -> str:
    return (
        f"contribution issue scan stopped after {scanned_items} items "
        f"because the scan budget ({max_scan_items}) was exhausted"
    )


def _mark_truncated(
    state: _CandidateScanState,
    warning: str,
) -> None:
    state.truncated = True

    if warning not in state.warnings:
        state.warnings.append(warning)


def _source_truncation_warning(
    source_name: str,
    scanned_items: int,
) -> str:
    return (
        f"contribution candidate scan for {source_name} stopped after "
        f"{scanned_items} items while more candidates were available"
    )


def _exception_details(error: Exception | None) -> dict[str, Any] | None:
    if error is None:
        return None

    return {
        "type": type(error).__name__,
        "message": str(error),
        "status_code": getattr(error, "status_code", None),
        "retry_after": getattr(error, "retry_after", None),
        "rate_limit_reset": getattr(error, "rate_limit_reset", None),
    }


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


def _validate_pagination_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise GitHubAPIError(
            f"Invalid GitHub pagination URL: {url!r}"
        ) from exc

    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != "api.github.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise GitHubAPIError(
            "Refusing to follow untrusted GitHub pagination URL: "
            f"{url!r}"
        )

    return url


def _next_page_url(
    response: httpx.Response,
    *,
    action: str,
) -> str | None:
    next_link = response.links.get("next")

    if next_link is None:
        return None

    if not isinstance(next_link, dict):
        raise GitHubAPIError(
            f"Malformed GitHub pagination response while {action}"
        )

    next_url = next_link.get("url")

    if not isinstance(next_url, str) or not next_url.strip():
        raise GitHubAPIError(
            "GitHub pagination response included a 'next' link "
            f"without a usable URL while {action}"
        )

    return _validate_pagination_url(next_url.strip())


def _fetch_page(
    url: str,
    *,
    params: dict[str, Any] | None,
    timeout: float,
    action: str,
    owner: str,
    repo: str,
) -> tuple[list[Any], httpx.Response]:
    _validate_pagination_url(url)

    try:
        response = httpx.get(
            url,
            headers=_github_headers(),
            params=params,
            timeout=timeout,
        )
    except (httpx.RequestError, httpx.InvalidURL) as exc:
        raise GitHubAPIError(
            f"Could not fetch contribution issues: {exc}"
        ) from exc

    error = _error_for_response(
        response,
        action=action,
        owner=owner,
        repo=repo,
    )

    if error is not None:
        raise error

    try:
        page_issues = _response_json(response, action=action)
    except GitHubAPIError as exc:
        raise _attach_response_details(exc, response) from exc

    if not isinstance(page_issues, list):
        raise GitHubAPIError(
            f"Unexpected GitHub issues response for {owner}/{repo}"
        )

    return page_issues, response


def _attach_response_details(
    error: Exception,
    response: httpx.Response,
) -> Exception:
    error.status_code = response.status_code

    retry_after = response.headers.get("Retry-After")
    rate_limit_reset = response.headers.get("X-RateLimit-Reset")

    if retry_after is not None:
        error.retry_after = retry_after

    if rate_limit_reset is not None:
        error.rate_limit_reset = rate_limit_reset

    return error


def _error_for_response(
    response: httpx.Response,
    *,
    action: str,
    owner: str,
    repo: str,
) -> Exception | None:
    if response.status_code == 200:
        return None

    details = []

    retry_after = response.headers.get("Retry-After")
    rate_limit_reset = response.headers.get("X-RateLimit-Reset")

    if retry_after is not None:
        details.append(f"Retry-After: {retry_after}")

    if rate_limit_reset is not None:
        details.append(f"X-RateLimit-Reset: {rate_limit_reset}")

    if response.status_code == 404:
        error = RepositoryNotFound(
            f"Repository {owner}/{repo} was not found or is not public"
        )
    elif response.status_code in (403, 429):
        message = (
            f"GitHub rate limit or access restriction reached while {action}"
        )

        if details:
            message = f"{message} ({'; '.join(details)})"

        error = GitHubAPIError(message)
    else:
        message = (
            f"GitHub API returned HTTP {response.status_code} while {action}"
        )

        if details:
            message = f"{message} ({'; '.join(details)})"

        error = GitHubAPIError(message)

    return _attach_response_details(error, response)


def _classify_issue(issue: dict, index: int) -> dict[str, Any] | None:
    if "pull_request" in issue:
        return None

    number = _required_issue_number(issue, index)
    title = _required_issue_string(issue, index, "title")
    url = _required_issue_string(issue, index, "html_url")
    labels = _issue_labels(issue, index)
    body = _issue_body(issue, index)

    normalized_labels = {
        _normalize_label(label)
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
        return None

    beginner_labelled = (
        strongly_beginner_labelled or help_wanted_labelled
    )

    starter_wording = any(
        keyword in title.lower()
        for keyword in TITLE_BEGINNER_KEYWORDS
    )

    if not beginner_labelled and not starter_wording:
        return None

    return {
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


def _budget_exhausted_result(
    issues: list[dict[str, Any]],
    scanned_items: int,
    pages_fetched: int,
    max_scan_items: int,
    warnings: list[str] | None = None,
) -> IssueDiscoveryResult:
    messages = list(warnings or [])
    total_warning = _total_budget_warning(
        scanned_items,
        max_scan_items,
    )

    if scanned_items >= max_scan_items:
        messages = [
            total_warning,
            *[message for message in messages if message != total_warning],
        ]
    elif not messages:
        messages = [total_warning]

    return IssueDiscoveryResult(
        issues=issues,
        status=IssueDiscoveryStatus.BUDGET_EXHAUSTED,
        scanned_items=scanned_items,
        pages_fetched=pages_fetched,
        warnings=messages,
    )


def _failed_result(
    error: Exception,
    issues: list[dict[str, Any]],
    scanned_items: int,
    pages_fetched: int,
    warnings: list[str] | None = None,
) -> IssueDiscoveryResult:
    return IssueDiscoveryResult(
        issues=issues,
        status=IssueDiscoveryStatus.FAILED,
        scanned_items=scanned_items,
        pages_fetched=pages_fetched,
        warnings=[
            f"could not fetch contribution issues: {error}",
            *(warnings or []),
        ],
        error=error,
    )


def _scan_candidate_source(
    state: _CandidateScanState,
    *,
    owner: str,
    repo: str,
    label: str | None,
    limit: int,
    timeout: float,
    max_scan_items: int,
    source_quota: int,
) -> bool:
    source_name = (
        f"label {label!r}"
        if label is not None
        else "mixed title fallback"
    )
    action = f"fetching issues for {owner}/{repo}"
    params: dict[str, Any] = {
        "state": "open",
        "sort": "created",
        "direction": "desc",
    }

    if label is not None:
        params["labels"] = label

    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    seen_urls: set[str] = set()
    source_scanned = 0
    first_page = True

    while True:
        if url in seen_urls:
            raise GitHubAPIError(
                f"GitHub pagination loop detected while {action}"
            )

        seen_urls.add(url)

        remaining_total = max_scan_items - state.scanned_items
        remaining_source = source_quota - source_scanned

        if remaining_total <= 0:
            _mark_truncated(
                state,
                _total_budget_warning(
                    state.scanned_items,
                    max_scan_items,
                ),
            )
            return False

        if remaining_source <= 0:
            _mark_truncated(
                state,
                _source_truncation_warning(
                    source_name,
                    source_scanned,
                ),
            )
            return False

        if first_page:
            params["per_page"] = min(
                MAX_ITEMS_PER_PAGE,
                remaining_total,
                remaining_source,
            )
            request_params: dict[str, Any] | None = params
        else:
            request_params = None

        page_issues, response = _fetch_page(
            url,
            params=request_params,
            timeout=timeout,
            action=action,
            owner=owner,
            repo=repo,
        )
        first_page = False
        state.pages_fetched += 1

        for index, issue in enumerate(page_issues):
            if state.scanned_items >= max_scan_items:
                _mark_truncated(
                    state,
                    _total_budget_warning(
                        state.scanned_items,
                        max_scan_items,
                    ),
                )
                return False

            if source_scanned >= source_quota:
                _mark_truncated(
                    state,
                    _source_truncation_warning(
                        source_name,
                        source_scanned,
                    ),
                )
                return False

            state.scanned_items += 1
            source_scanned += 1

            if not isinstance(issue, dict):
                raise GitHubAPIError(
                    "Malformed GitHub issue response at index "
                    f"{index}: expected an object"
                )

            result = _classify_issue(issue, index)

            if result is None:
                continue

            issue_number = result["number"]

            if issue_number in state.issue_numbers:
                continue

            state.issue_numbers.add(issue_number)
            state.issues.append(result)

            if len(state.issues) >= limit:
                more_in_page = index + 1 < len(page_issues)
                next_url = _next_page_url(response, action=action)

                if more_in_page or next_url is not None:
                    if state.scanned_items >= max_scan_items:
                        _mark_truncated(
                            state,
                            _total_budget_warning(
                                state.scanned_items,
                                max_scan_items,
                            ),
                        )
                    elif source_scanned >= source_quota:
                        _mark_truncated(
                            state,
                            _source_truncation_warning(
                                source_name,
                                source_scanned,
                            ),
                        )

                return True

        next_url = _next_page_url(response, action=action)

        if next_url is None:
            return False

        if state.scanned_items >= max_scan_items:
            _mark_truncated(
                state,
                _total_budget_warning(
                    state.scanned_items,
                    max_scan_items,
                ),
            )
            return False

        if source_scanned >= source_quota:
            _mark_truncated(
                state,
                _source_truncation_warning(
                    source_name,
                    source_scanned,
                ),
            )
            return False

        url = next_url


def discover_contribution_issues(
    owner: str,
    repo: str,
    limit: int = 10,
    timeout: float = 15.0,
    max_scan_items: int = DEFAULT_MAX_SCAN_ITEMS,
) -> IssueDiscoveryResult:
    """Discover beginner-friendly issues with bounded label retrieval."""
    if limit <= 0:
        return IssueDiscoveryResult()

    if max_scan_items <= 0:
        return _budget_exhausted_result(
            [],
            0,
            0,
            max_scan_items,
        )

    state = _CandidateScanState()
    sources: list[str | None] = [*CANDIDATE_LABELS, None]

    try:
        for index, label in enumerate(sources):
            remaining_total = max_scan_items - state.scanned_items

            if remaining_total <= 0:
                _mark_truncated(
                    state,
                    _total_budget_warning(
                        state.scanned_items,
                        max_scan_items,
                    ),
                )
                break

            remaining_sources = len(sources) - index
            source_quota = min(
                remaining_total,
                max(1, remaining_total // remaining_sources),
            )

            limit_reached = _scan_candidate_source(
                state,
                owner=owner,
                repo=repo,
                label=label,
                limit=limit,
                timeout=timeout,
                max_scan_items=max_scan_items,
                source_quota=source_quota,
            )

            if limit_reached:
                if state.truncated:
                    return _budget_exhausted_result(
                        state.issues,
                        state.scanned_items,
                        state.pages_fetched,
                        max_scan_items,
                        state.warnings,
                    )

                return IssueDiscoveryResult(
                    issues=state.issues,
                    status=IssueDiscoveryStatus.COMPLETE,
                    scanned_items=state.scanned_items,
                    pages_fetched=state.pages_fetched,
                )

            if (
                state.scanned_items >= max_scan_items
                and index < len(sources) - 1
            ):
                _mark_truncated(
                    state,
                    _total_budget_warning(
                        state.scanned_items,
                        max_scan_items,
                    ),
                )
                break

    except (GitHubAPIError, RepositoryNotFound) as exc:
        return _failed_result(
            exc,
            state.issues,
            state.scanned_items,
            state.pages_fetched,
            state.warnings,
        )

    if state.truncated:
        return _budget_exhausted_result(
            state.issues,
            state.scanned_items,
            state.pages_fetched,
            max_scan_items,
            state.warnings,
        )

    return IssueDiscoveryResult(
        issues=state.issues,
        status=IssueDiscoveryStatus.COMPLETE,
        scanned_items=state.scanned_items,
        pages_fetched=state.pages_fetched,
    )


def find_first_contribution_issues(
    owner: str,
    repo: str,
    limit: int = 10,
    timeout: float = 15.0,
    max_scan_items: int = DEFAULT_MAX_SCAN_ITEMS,
) -> list[dict[str, Any]]:
    """Return open issues suitable for a first contribution."""
    result = discover_contribution_issues(
        owner,
        repo,
        limit=limit,
        timeout=timeout,
        max_scan_items=max_scan_items,
    )

    if result.error is not None:
        raise result.error

    return result.issues
