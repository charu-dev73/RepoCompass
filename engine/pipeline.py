"""Run the Phase 1 steps: URL -> download -> extract -> discover -> parse."""

from dataclasses import dataclass
from pathlib import Path

from engine.discover import DiscoveryResult, find_python_files
from engine.fetch import download_repo_zip, extract_repo_zip, parse_github_url
from engine.parse import FileInfo, parse_files


@dataclass
class RepoSnapshot:
    owner: str
    repo: str
    root: Path
    discovery: DiscoveryResult
    files: list[FileInfo]


def load_repository(url: str, workdir: Path) -> RepoSnapshot:
    """Fetch a public GitHub repo, discover its Python files, and parse them."""
    owner, repo = parse_github_url(url)

    zip_path = download_repo_zip(owner, repo, workdir)

    root = extract_repo_zip(
        zip_path,
        workdir / "extracted",
    )

    discovery = find_python_files(root)

    files = parse_files(root, discovery.python_files)

    return RepoSnapshot(
        owner=owner,
        repo=repo,
        root=root,
        discovery=discovery,
        files=files,
    )
