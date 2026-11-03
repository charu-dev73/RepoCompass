
"""Load and analyze a Python repository."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.discover import DiscoveryResult, find_python_files
from engine.entrypoints import detect_entrypoints
from engine.fetch import (
    GitHubAPIError,
    download_repo_zip,
    extract_repo_zip,
    parse_github_url,
)
from engine.graph import DependencyGraph, build_dependency_graph
from engine.issues import find_first_contribution_issues
from engine.parse import FileInfo, parse_files
from engine.reading_path import ReadingStep, generate_reading_path
from engine.resolve import build_module_map


@dataclass
class RepoSnapshot:
    owner: str
    repo: str
    root: Path
    discovery: DiscoveryResult
    files: list[FileInfo]
    graph: DependencyGraph = field(default_factory=DependencyGraph)
    entrypoints: list[Path] = field(default_factory=list)
    reading_path: list[ReadingStep] = field(default_factory=list)
    contribution_issues: list[dict[str, Any]] = field(default_factory=list)


def load_repository(
    url: str,
    workdir: Path,
    fetch_issues: bool = False,
) -> RepoSnapshot:
    """Download and analyze a repository.

    Issue fetching is optional so ordinary analysis and tests don't
    require a separate GitHub API request.
    """
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
    entrypoints = detect_entrypoints(files, graph)
    reading_path = generate_reading_path(graph, entrypoints)

    contribution_issues: list[dict[str, Any]] = []

    if fetch_issues:
        try:
            contribution_issues = find_first_contribution_issues(
                owner,
                repo,
            )
        except GitHubAPIError as exc:
            print(f"Warning: could not fetch contribution issues: {exc}")

    return RepoSnapshot(
        owner=owner,
        repo=repo,
        root=root,
        discovery=discovery,
        files=files,
        graph=graph,
        entrypoints=entrypoints,
        reading_path=reading_path,
        contribution_issues=contribution_issues,
    )
