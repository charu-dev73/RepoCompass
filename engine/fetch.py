"""Fetch a public GitHub repository so it can be analysed."""

import os
import re
from urllib.parse import urlparse

import httpx


class InvalidGitHubURL(ValueError):
    """Raised when a string is not a usable public GitHub repository URL."""


# GitHub owner and repo names only use letters, digits, '-', '_' and '.'
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_valid_name(name: str) -> bool:
    return bool(_NAME_PATTERN.match(name)) and name not in (".", "..")


def parse_github_url(url: str) -> tuple[str, str]:
    """Return (owner, repo) from a GitHub repository URL."""
    parsed = urlparse(url.strip())

    if parsed.scheme not in ("http", "https"):
        raise InvalidGitHubURL(f"URL must start with http:// or https://: {url!r}")

    if parsed.netloc.lower() not in ("github.com", "www.github.com"):
        raise InvalidGitHubURL(f"Not a github.com URL: {url!r}")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise InvalidGitHubURL(
            f"URL must look like https://github.com/<owner>/<repo>: {url!r}"
        )

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    if not _is_valid_name(owner) or not _is_valid_name(repo):
        raise InvalidGitHubURL(f"Invalid owner or repository name: {url!r}")

    return owner, repo
GITHUB_API = "https://api.github.com"


class RepositoryNotFound(Exception):
    """Raised when the repository does not exist or is not public."""


class GitHubAPIError(Exception):
    """Raised when GitHub cannot be reached or returns an unexpected response."""


def get_repo_info(owner: str, repo: str, timeout: float = 10.0) -> dict:
    """Ask GitHub for basic facts about a repository."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RepoCompass",
    }

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = httpx.get(
            f"{GITHUB_API}/repos/{owner}/{repo}",
            headers=headers,
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise GitHubAPIError(f"Could not reach GitHub: {exc}") from exc

    if response.status_code == 404:
        raise RepositoryNotFound(
            f"{owner}/{repo} not found, or it is not public"
        )

    if response.status_code in (403, 429):
        raise GitHubAPIError(
            "GitHub refused the request (likely rate limit reached)"
        )

    if response.status_code != 200:
        raise GitHubAPIError(
            f"Unexpected GitHub response: {response.status_code}"
        )

    data = response.json()

    return {
        "full_name": data["full_name"],
        "default_branch": data["default_branch"],
        "size_kb": data["size"],
        "language": data["language"],
    }