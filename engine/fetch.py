import lzma
import os
import re
import zipfile
import zlib
from pathlib import Path, PurePosixPath
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


def _raise_for_github_status(
    response: httpx.Response,
    *,
    action: str,
    not_found_error: type[Exception],
    not_found_message: str,
) -> None:
    """Raise the appropriate RepoCompass error for a GitHub status code."""
    if response.status_code == 404:
        raise not_found_error(not_found_message)

    if response.status_code in (403, 429):
        raise GitHubAPIError(
            f"GitHub rate limit or access restriction reached while {action}"
        )

    if response.status_code != 200:
        raise GitHubAPIError(
            f"GitHub API returned HTTP {response.status_code} while {action}"
        )


def _response_json(
    response: httpx.Response,
    *,
    action: str,
) -> object:
    """Decode a GitHub JSON response, converting malformed JSON to our error."""
    try:
        return response.json()
    except ValueError as exc:
        raise GitHubAPIError(
            f"GitHub returned invalid JSON while {action}"
        ) from exc


def _required_string(
    data: dict,
    field: str,
) -> str:
    value = data.get(field)

    if not isinstance(value, str) or not value:
        raise GitHubAPIError(
            f"Malformed GitHub response: '{field}' must be a non-empty string"
        )

    return value


def _required_size(data: dict) -> int:
    value = data.get("size")

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GitHubAPIError(
            "Malformed GitHub response: 'size' must be a non-negative integer"
        )

    return value


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

    action = f"fetching metadata for {owner}/{repo}"

    _raise_for_github_status(
        response,
        action=action,
        not_found_error=RepositoryNotFound,
        not_found_message=f"{owner}/{repo} not found, or it is not public",
    )

    data = _response_json(response, action=action)

    if not isinstance(data, dict):
        raise GitHubAPIError(
            f"Unexpected GitHub metadata response for {owner}/{repo}"
        )

    language = data.get("language")

    if language is not None and not isinstance(language, str):
        raise GitHubAPIError(
            "Malformed GitHub response: 'language' must be a string or null"
        )

    return {
        "full_name": _required_string(data, "full_name"),
        "default_branch": _required_string(data, "default_branch"),
        "size_kb": _required_size(data),
        "language": language,
    }


MAX_REPO_SIZE_KB = 200_000
MAX_ZIP_BYTES = 50 * 1024 * 1024


class RepositoryTooLarge(Exception):
    """Raised when a repository exceeds RepoCompass's size limits."""


def _remove_partial_download(zip_path: Path) -> None:
    """Best-effort removal of an incomplete archive."""
    try:
        zip_path.unlink(missing_ok=True)
    except OSError:
        pass


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
                _remove_partial_download(zip_path)

            _raise_for_github_status(
                response,
                action=f"downloading {owner}/{repo}",
                not_found_error=RepositoryNotFound,
                not_found_message=f"{owner}/{repo} not found, or it is not public",
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
        _remove_partial_download(zip_path)
        raise GitHubAPIError(
            f"Could not download repository: {exc}"
        ) from exc

    except RepositoryTooLarge:
        _remove_partial_download(zip_path)
        raise

    except OSError:
        _remove_partial_download(zip_path)
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


def _is_regular_file_or_directory(member: zipfile.ZipInfo) -> bool:
    """Validate Unix entry types against filename directory semantics."""
    unix_mode = (member.external_attr >> 16) & 0o170000

    if unix_mode == 0:
        return True

    if unix_mode not in (0o100000, 0o040000):
        return False

    if unix_mode == 0o040000 and not member.is_dir():
        raise UnsafeArchiveError(
            f"Directory entry must end with '/': {member.filename!r}"
        )

    if unix_mode == 0o100000 and member.is_dir():
        raise UnsafeArchiveError(
            f"Regular file entry must not end with '/': "
            f"{member.filename!r}"
        )

    return True


def _validate_archive_path(filename: str) -> PurePosixPath:
    """Validate a ZIP path before using it on the filesystem."""
    if not filename or "\\" in filename:
        raise UnsafeArchiveError(
            f"Unsafe path in archive: {filename!r}"
        )

    archive_path = PurePosixPath(filename)

    if archive_path.is_absolute():
        raise UnsafeArchiveError(
            f"Unsafe path in archive: {filename}"
        )

    if ".." in archive_path.parts:
        raise UnsafeArchiveError(
            f"Unsafe path in archive: {filename}"
        )

    if not archive_path.parts:
        raise UnsafeArchiveError(
            f"Unsafe path in archive: {filename}"
        )

    if re.match(r"^[A-Za-z]:", archive_path.parts[0]):
        raise UnsafeArchiveError(
            f"Unsafe path in archive: {filename}"
        )

    return archive_path


def _validate_destination_path(dest_dir: Path) -> Path:
    """Resolve a destination without user-controlled symlink components."""
    absolute_path = dest_dir.absolute()
    current = Path(absolute_path.anchor)

    for index, part in enumerate(absolute_path.parts[1:], start=1):
        current = current / part

        # Allow root-level system aliases such as macOS /var -> /private/var.
        # Deeper symlinks could redirect extraction and must be rejected.
        if index == 1:
            continue

        if current.is_symlink():
            raise UnsafeArchiveError(
                f"Destination path contains a symbolic link: {current}"
            )

    return absolute_path.resolve()


def _create_destination_directory(
    path: Path,
    created_paths: list[Path],
) -> None:
    """Create destination and parents, recording new directories."""
    current = Path(path.anchor)

    for part in path.parts[1:]:
        current = current / part

        if current.exists():
            if current.is_symlink():
                raise UnsafeArchiveError(
                    f"Destination path contains a symbolic link: {current}"
                )

            if not current.is_dir():
                raise UnsafeArchiveError(
                    f"Extraction destination is not a directory: {current}"
                )

            continue

        try:
            current.mkdir()
        except FileExistsError:
            if not current.is_dir():
                raise UnsafeArchiveError(
                    f"Extraction destination is not a directory: {current}"
                )
            continue
        except OSError as exc:
            raise UnsafeArchiveError(
                f"Could not create extraction destination {current}: {exc}"
            ) from exc

        created_paths.append(current)


def _check_existing_symlinks(
    destination_root: Path,
    target_path: Path,
) -> None:
    """Prevent extraction through existing symbolic links."""
    current = destination_root

    relative_path = target_path.relative_to(destination_root)

    for part in relative_path.parts:
        current = current / part

        if current.is_symlink():
            raise UnsafeArchiveError(
                f"Extraction would follow an existing symbolic link: "
                f"{current}"
            )


def _reject_file_directory_collisions(
    safe_members: list[tuple[zipfile.ZipInfo, Path, PurePosixPath]],
) -> None:
    """Reject archives where a file is also required to be a directory."""
    file_paths = {
        archive_path.parts: archive_path
        for member, _, archive_path in safe_members
        if not member.is_dir()
    }

    for member, _, archive_path in safe_members:
        parts = archive_path.parts

        for length in range(1, len(parts)):
            parent = file_paths.get(parts[:length])

            if parent is not None:
                raise UnsafeArchiveError(
                    f"Archive entry '{archive_path}' is nested under "
                    f"file '{parent}'"
                )


def _ensure_directory(
    path: Path,
    destination_root: Path,
    created_paths: list[Path],
) -> None:
    """Create missing directories, recording only the ones we create."""
    relative_path = path.relative_to(destination_root)

    current = destination_root

    for part in relative_path.parts:
        current = current / part

        if current.exists():
            if not current.is_dir():
                raise UnsafeArchiveError(
                    f"Archive requires a directory where a file exists: "
                    f"{current}"
                )
            continue

        current.mkdir()
        created_paths.append(current)


def _cleanup_failed_extraction(created_paths: list[Path]) -> None:
    """Remove only extraction artifacts created by the failed call."""
    for path in reversed(created_paths):
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
        except OSError:
            pass


def _read_archive_chunk(
    source: zipfile.ZipExtFile,
    member: zipfile.ZipInfo,
    zip_path: Path,
) -> bytes:
    """Read a member chunk and translate decompression failures."""
    try:
        return source.read(64 * 1024)
    except (
        zipfile.BadZipFile,
        zlib.error,
        lzma.LZMAError,
        EOFError,
    ) as exc:
        raise InvalidArchiveError(
            f"Invalid or corrupt ZIP archive: {zip_path}"
        ) from exc
    except OSError as exc:
        if member.compress_type != zipfile.ZIP_BZIP2:
            raise

        raise InvalidArchiveError(
            f"Invalid or corrupt ZIP archive: {zip_path}"
        ) from exc


def extract_repo_zip(
    zip_path: Path,
    dest_dir: Path,
) -> Path:
    """Safely extract regular files and reject existing targets."""

    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)

    destination_root = _validate_destination_path(dest_dir)

    created_paths: list[Path] = []

    try:
        _create_destination_directory(
            destination_root,
            created_paths,
        )

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
            seen_paths: dict[tuple[str, ...], str] = {}
            safe_members = []

            for member in members:
                if not member.filename:
                    raise UnsafeArchiveError(
                        "Archive entry has an empty filename"
                    )

                member_path = _validate_archive_path(
                    member.filename
                )

                if member_path.parts in seen_paths:
                    raise UnsafeArchiveError(
                        f"Duplicate path in archive: "
                        f"{member.filename!r} conflicts with "
                        f"{seen_paths[member_path.parts]!r}"
                    )

                seen_paths[member_path.parts] = member.filename
                top_level_dirs.add(member_path.parts[0])

                # Symlinks are deliberately skipped, not extracted.
                if _is_symlink(member):
                    continue

                if not _is_regular_file_or_directory(member):
                    raise UnsafeArchiveError(
                        f"Unsupported special file in archive: "
                        f"{member.filename}"
                    )

                target_path = destination_root.joinpath(
                    *member_path.parts
                )

                try:
                    target_path.relative_to(destination_root)
                except ValueError as exc:
                    raise UnsafeArchiveError(
                        f"Archive entry escapes destination: "
                        f"{member.filename}"
                    ) from exc

                _check_existing_symlinks(
                    destination_root,
                    target_path,
                )

                safe_members.append(
                    (member, target_path, member_path)
                )

            if len(top_level_dirs) != 1:
                raise UnsafeArchiveError(
                    "Repository ZIP must contain exactly one "
                    "top-level directory"
                )

            _reject_file_directory_collisions(safe_members)

            top_level_dir = next(iter(top_level_dirs))
            extracted_bytes = 0

            for member, target_path, _ in safe_members:
                try:
                    _check_existing_symlinks(
                        destination_root,
                        target_path,
                    )

                    if member.is_dir():
                        _ensure_directory(
                            target_path,
                            destination_root,
                            created_paths,
                        )
                        continue

                    _ensure_directory(
                        target_path.parent,
                        destination_root,
                        created_paths,
                    )

                    if target_path.exists() or target_path.is_symlink():
                        raise UnsafeArchiveError(
                            f"Refusing to overwrite existing extraction "
                            f"target: {target_path}"
                        )

                    with archive.open(member) as source:
                        with target_path.open("xb") as destination:
                            created_paths.append(target_path)

                            while True:
                                chunk = _read_archive_chunk(
                                    source,
                                    member,
                                    zip_path,
                                )

                                if not chunk:
                                    break

                                if extracted_bytes + len(chunk) > MAX_EXTRACT_BYTES:
                                    raise UnsafeArchiveError(
                                        "Repository ZIP extraction would exceed "
                                        f"the {MAX_EXTRACT_BYTES} byte limit"
                                    )

                                destination.write(chunk)
                                extracted_bytes += len(chunk)

                except OSError as exc:
                    raise UnsafeArchiveError(
                        f"Could not safely extract archive entry "
                        f"{member.filename!r}: {exc}"
                    ) from exc

            extracted_root = destination_root / top_level_dir

            if extracted_root.is_symlink() or not extracted_root.is_dir():
                raise UnsafeArchiveError(
                    "Expected repository root directory was not extracted "
                    "as a real directory"
                )

    except (zipfile.BadZipFile, zlib.error, lzma.LZMAError) as exc:
        _cleanup_failed_extraction(created_paths)
        raise InvalidArchiveError(
            f"Invalid or corrupt ZIP archive: {zip_path}"
        ) from exc

    except Exception:
        _cleanup_failed_extraction(created_paths)
        raise

    return dest_dir / top_level_dir
