"""Run the Phase 1 steps: URL -> downloaded, extracted repo -> Python files."""

from dataclasses import dataclass
from pathlib import Path

from engine.discover import DiscoveryResult, find_python_files
from engine.fetch import download_repo_zip, extract_repo_zip, parse_github_url


@dataclass
class RepoSnapshot:
    owner: str
    repo: str
    root: Path
    discovery: DiscoveryResult


def load_repository(url: str, workdir: Path) -> RepoSnapshot:
    """Fetch a public GitHub repo into workdir and list its Python files."""
    owner, repo = parse_github_url(url)

    zip_path = download_repo_zip(owner, repo, workdir)

    root = extract_repo_zip(
        zip_path,
        workdir / "extracted",
    )

    discovery = find_python_files(root)

    return RepoSnapshot(
        owner=owner,
        repo=repo,
        root=root,
        discovery=discovery,
    )