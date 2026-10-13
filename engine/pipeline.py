
"""Load and analyze a Python repository."""

from dataclasses import dataclass, field
from pathlib import Path

from engine.discover import DiscoveryResult, find_python_files
from engine.fetch import download_repo_zip, extract_repo_zip, parse_github_url
from engine.graph import DependencyGraph, build_dependency_graph
from engine.parse import FileInfo, parse_files
from engine.resolve import build_module_map


@dataclass
class RepoSnapshot:
    owner: str
    repo: str
    root: Path
    discovery: DiscoveryResult
    files: list[FileInfo]
    graph: DependencyGraph = field(default_factory=DependencyGraph)


def load_repository(url: str, workdir: Path) -> RepoSnapshot:
    """Fetch, discover, parse, and build a dependency graph for a repository."""
    owner, repo = parse_github_url(url)

    zip_path = download_repo_zip(owner, repo, workdir)

    root = extract_repo_zip(
        zip_path,
        workdir / "extracted",
    )

    discovery = find_python_files(root)
    files = parse_files(root, discovery.python_files)

    module_map = build_module_map(discovery.python_files)
    graph = build_dependency_graph(files, module_map)

    return RepoSnapshot(
        owner=owner,
        repo=repo,
        root=root,
        discovery=discovery,
        files=files,
        graph=graph,
    )
