import os
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx


class InvalidGitHubURL(ValueError):
    """Raised when a string is not a usable public GitHub repository URL."""


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_valid_name(name: str) -> bool:
    return bool(_NAME_PATTERN.match(name)) and name not in (".", "..")


def parse_github_url(url: str) -> tuple[str, str]:
    """Return (owner, repo) from a GitHub repository URL."""
    parsed = urlparse(url.strip())

    if parsed.scheme not in ("http", "https"):
        raise InvalidGitHubURL(
            f"URL must start with http:// or https://: {url!r}"
        )

    if parsed.netloc.lower() not in ("github.com", "www.github.com"):
        raise InvalidGitHubURL(
            f"Not a github.com URL: {url!r}"
        )

    parts = [p for p in parsed.path.split("/") if p]

    if len(parts) < 2:
        raise InvalidGitHubURL(
            f"URL must look like https://github.com/<owner>/<repo>: {url!r}"
        )

    owner, repo = parts[0], parts[1]

    if repo.endswith(".git"):
        repo = repo[:-4]

    if not _is_valid_name(owner) or not _is_valid_name(repo):
        raise InvalidGitHubURL(
            f"Invalid owner or repository name: {url!r}"
        )

    return owner, repo


GITHUB_API = "https://api.github.com"


class RepositoryNotFound(Exception):
    """Raised when the repository does not exist or is not public."""


class GitHubAPIError(Exception):
    """Raised when GitHub cannot be reached or returns an unexpected response."""


def _github_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RepoCompass",
    }

    token = os.environ.get("GITHUB_TOKEN")

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def get_repo_info(
    owner: str,
    repo: str,
    timeout: float = 10.0,
) -> dict:
    """Ask GitHub for basic facts about a repository."""
    headers = _github_headers()

    try:
        response = httpx.get(
            f"{GITHUB_API}/repos/{owner}/{repo}",
            headers=headers,
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        raise GitHubAPIError(
            f"Could not reach GitHub: {exc}"
        ) from exc

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


MAX_REPO_SIZE_KB = 200_000
MAX_ZIP_BYTES = 50 * 1024 * 1024


class RepositoryTooLarge(Exception):
    """Raised when a repository exceeds RepoCompass's size limits."""


def download_repo_zip(
    owner: str,
    repo: str,
    dest_dir: Path,
    timeout: float = 30.0,
) -> Path:
    """Download the default branch of a repository as a zip into dest_dir."""

    info = get_repo_info(owner, repo)

    if info["size_kb"] > MAX_REPO_SIZE_KB:
        raise RepositoryTooLarge(
            f"{owner}/{repo} is {info['size_kb']} KB, "
            f"over the {MAX_REPO_SIZE_KB} KB limit"
        )

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    zip_path = dest_dir / "repo.zip"

    url = f"{GITHUB_API}/repos/{owner}/{repo}/zipball"

    try:
        with httpx.stream(
            "GET",
            url,
            headers=_github_headers(),
            follow_redirects=True,
            timeout=timeout,
        ) as response:

            if response.status_code != 200:
                raise GitHubAPIError(
                    f"Download failed with status {response.status_code}"
                )

            total = 0

            with open(zip_path, "wb") as f:
                for chunk in response.iter_bytes():
                    total += len(chunk)

                    if total > MAX_ZIP_BYTES:
                        raise RepositoryTooLarge(
                            f"Download passed the {MAX_ZIP_BYTES} "
                            f"byte limit; stopped"
                        )

                    f.write(chunk)

    except httpx.RequestError as exc:
        zip_path.unlink(missing_ok=True)
        raise GitHubAPIError(
            f"Could not download repository: {exc}"
        ) from exc

    except RepositoryTooLarge:
        zip_path.unlink(missing_ok=True)
        raise

    return zip_path


class UnsafeArchiveError(Exception):
    """Raised when a ZIP archive contains an unsafe path or structure."""


class InvalidArchiveError(Exception):
    """Raised when the ZIP archive is corrupt or invalid."""


MAX_EXTRACT_BYTES = 200 * 1024 * 1024
MAX_EXTRACT_FILES = 10_000


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    """Return True when a ZIP member represents a symbolic link."""

    unix_mode = (member.external_attr >> 16) & 0o170000

    return unix_mode == 0o120000


def extract_repo_zip(
    zip_path: Path,
    dest_dir: Path,
) -> Path:
    """Safely extract a repository ZIP and return its top-level directory."""

    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.infolist()

            if not members:
                raise UnsafeArchiveError(
                    "Repository ZIP is empty"
                )

            if len(members) > MAX_EXTRACT_FILES:
                raise UnsafeArchiveError(
                    f"Repository ZIP contains too many files: "
                    f"{len(members)} > {MAX_EXTRACT_FILES}"
                )

            total_uncompressed_size = sum(
                member.file_size for member in members
            )

            if total_uncompressed_size > MAX_EXTRACT_BYTES:
                raise UnsafeArchiveError(
                    f"Repository ZIP expands to "
                    f"{total_uncompressed_size} bytes, "
                    f"over the {MAX_EXTRACT_BYTES} byte limit"
                )

            top_level_dirs = set()
            destination_root = dest_dir.resolve()

            for member in members:
                member_path = Path(member.filename)

                if member_path.is_absolute() or ".." in member_path.parts:
                    raise UnsafeArchiveError(
                        f"Unsafe path in archive: {member.filename}"
                    )

                if _is_symlink(member):
                    raise UnsafeArchiveError(
                        f"Symbolic links are not allowed: "
                        f"{member.filename}"
                    )

                if not member.filename:
                    continue

                top_level_dirs.add(member_path.parts[0])

                target_path = (
                    destination_root / member_path
                ).resolve()

                try:
                    target_path.relative_to(destination_root)
                except ValueError as exc:
                    raise UnsafeArchiveError(
                        f"Archive entry escapes destination: "
                        f"{member.filename}"
                    ) from exc

            if len(top_level_dirs) != 1:
                raise UnsafeArchiveError(
                    "Repository ZIP must contain exactly one "
                    "top-level directory"
                )

            top_level_dir = next(iter(top_level_dirs))

            archive.extractall(dest_dir)

    except zipfile.BadZipFile as exc:
        raise InvalidArchiveError(
            f"Invalid or corrupt ZIP archive: {zip_path}"
        ) from exc

    extracted_root = dest_dir / top_level_dir

    if not extracted_root.is_dir():
        raise UnsafeArchiveError(
            "Expected repository root directory was not extracted"
        )

    return extracted_root