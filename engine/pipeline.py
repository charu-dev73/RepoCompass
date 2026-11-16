
"""Load and analyze a Python repository."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.discover import (
    DiscoveryResult,
    DocDiscoveryResult,
    find_doc_files,
    find_python_files,
)
from engine.doc_issue_mapping import map_issue_to_docs
from engine.entrypoints import detect_entrypoint_groups
from engine.fetch import (
    GitHubAPIError,
    RepositoryNotFound,
    download_repo_zip,
    extract_repo_zip,
    parse_github_url,
)
from engine.graph import DependencyGraph, build_dependency_graph
from engine.issue_mapping import map_issue_to_files
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
    doc_discovery: DocDiscoveryResult = field(
        default_factory=DocDiscoveryResult
    )
    graph: DependencyGraph = field(default_factory=DependencyGraph)
    entrypoints: list[Path] = field(default_factory=list)
    secondary_entrypoints: list[Path] = field(default_factory=list)
    reading_path: list[ReadingStep] = field(default_factory=list)
    contribution_issues: list[dict[str, Any]] = field(default_factory=list)
    issue_file_matches: dict[int, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    issue_doc_matches: dict[int, list[dict[str, Any]]] = field(
        default_factory=dict
    )


def load_repository(
    url: str,
    workdir: Path,
    fetch_issues: bool = False,
) -> RepoSnapshot:
    """Download and analyze a repository."""
    owner, repo = parse_github_url(url)
    workdir = Path(workdir).resolve()

    zip_path = download_repo_zip(owner, repo, workdir)

    root = extract_repo_zip(
        zip_path,
        workdir / "extracted",
    )

    discovery = find_python_files(root)
    doc_discovery = find_doc_files(root)

    files = parse_files(root, discovery.python_files)

    module_map = build_module_map(discovery.python_files)
    graph = build_dependency_graph(files, module_map)
    entrypoint_groups = detect_entrypoint_groups(files, graph)
    entrypoints = entrypoint_groups.primary
    secondary_entrypoints = entrypoint_groups.secondary
    reading_path = generate_reading_path(
        graph,
        entrypoints,
        secondary_entrypoints=secondary_entrypoints,
        file_infos=files,
    )

    contribution_issues: list[dict[str, Any]] = []
    issue_file_matches: dict[int, list[dict[str, Any]]] = {}
    issue_doc_matches: dict[int, list[dict[str, Any]]] = {}

    if fetch_issues:
        try:
            contribution_issues = find_first_contribution_issues(
                owner,
                repo,
            )

            for issue in contribution_issues:
                issue_number = issue.get("number")

                if issue_number is None:
                    continue

                issue_file_matches[issue_number] = map_issue_to_files(
                    issue,
                    files,
                )

                issue_doc_matches[issue_number] = map_issue_to_docs(
                    issue,
                    doc_discovery.doc_files,
                    root,
                )

        except (GitHubAPIError, RepositoryNotFound) as exc:
            print(f"Warning: could not fetch contribution issues: {exc}")

    return RepoSnapshot(
        owner=owner,
        repo=repo,
        root=root,
        discovery=discovery,
        files=files,
        doc_discovery=doc_discovery,
        graph=graph,
        entrypoints=entrypoints,
        secondary_entrypoints=secondary_entrypoints,
        reading_path=reading_path,
        contribution_issues=contribution_issues,
        issue_file_matches=issue_file_matches,
        issue_doc_matches=issue_doc_matches,
    )
