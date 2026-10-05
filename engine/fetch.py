"""Fetch a public GitHub repository so it can be analysed."""

import re
from urllib.parse import urlparse


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