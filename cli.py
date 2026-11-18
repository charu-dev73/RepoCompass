
import sys
import tempfile
from pathlib import Path

from engine.fetch import (
    GitHubAPIError,
    InvalidArchiveError,
    InvalidGitHubURL,
    RepositoryNotFound,
    RepositoryTooLarge,
    UnsafeArchiveError,
)
from engine.pipeline import load_repository


EXPECTED_ERRORS = (
    InvalidGitHubURL,
    RepositoryNotFound,
    RepositoryTooLarge,
    GitHubAPIError,
    UnsafeArchiveError,
    InvalidArchiveError,
)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python cli.py <github-url>")
        return 2

    repo_url = sys.argv[1]

    print("RepoCompass")
    print(f"Repository: {repo_url}")

    try:
        with tempfile.TemporaryDirectory(prefix="repocompass-") as tmp:
            snapshot = load_repository(
                repo_url,
                Path(tmp),
                fetch_issues=True,
            )

            discovered_files = snapshot.discovery.python_files
            skipped = snapshot.discovery.skipped_dirs
            parsed_files = snapshot.files
            discovered_docs = snapshot.doc_discovery.doc_files

            main_guards = [
                info for info in parsed_files if info.has_main_guard
            ]
            parse_errors = [
                info for info in parsed_files
                if info.parse_error is not None
            ]

            print(f"\nAnalysed: {snapshot.owner}/{snapshot.repo}")
            print(f"Python files discovered: {len(discovered_files)}")
            print(f"Python files parsed: {len(parsed_files)}")
            print(f"Documentation files discovered: {len(discovered_docs)}")
            print(f"Files with main guard: {len(main_guards)}")
            print(f"Files with parse errors: {len(parse_errors)}")
            print(f"Skipped directories: {len(skipped)}")
            print(
                f"Dependency graph nodes: "
                f"{len(snapshot.graph.nodes())}"
            )
            print(
                f"Dependency graph edges: "
                f"{len(snapshot.graph.edges())}"
            )

            if snapshot.entrypoints:
                print("\nDetected entry points:")
                for path in snapshot.entrypoints:
                    print(f"  - {path}")
            elif not snapshot.secondary_entrypoints:
                print("\nNo likely entry points detected.")

            if snapshot.secondary_entrypoints:
                print("\nSecondary entry points:")
                for path in snapshot.secondary_entrypoints:
                    print(f"  - {path}")

            if snapshot.reading_path:
                print("\nSuggested reading path:")
                for step in snapshot.reading_path:
                    print(f"  {step.order}. {step.path}")
                    print(f"     Why: {step.reason}")
            else:
                print("\nNo reading path could be generated.")

            print("\nBeginner-friendly contribution issues:")
            issue_discovery = snapshot.issue_discovery
            issue_status = (
                issue_discovery.get("status")
                if issue_discovery
                else None
            )
            issue_failure = issue_status == "failed"

            if issue_status == "failed":
                scanned_items = (
                    issue_discovery.get("scanned_items", 0)
                    if issue_discovery
                    else 0
                )
                print("  Issue discovery failed.")
                print(
                    "  Issues found before failure: "
                    f"{len(snapshot.contribution_issues)}"
                )
                print(f"  Items scanned: {scanned_items}")
            elif issue_status == "budget_exhausted":
                scanned_items = (
                    issue_discovery.get("scanned_items", 0)
                    if issue_discovery
                    else 0
                )
                print("  Issue scan incomplete (scan budget exhausted).")
                print(
                    "  Issues found: "
                    f"{len(snapshot.contribution_issues)}"
                )
                print(f"  Items scanned: {scanned_items}")

            if snapshot.contribution_issues:
                for issue in snapshot.contribution_issues:
                    issue_number = issue["number"]

                    print(f"\n  #{issue_number}: {issue['title']}")
                    print(f"  URL: {issue['url']}")
                    print(
                        f"  Labels: "
                        f"{', '.join(issue.get('labels', []))}"
                    )

                    python_matches = snapshot.issue_file_matches.get(
                        issue_number,
                        [],
                    )
                    doc_matches = snapshot.issue_doc_matches.get(
                        issue_number,
                        [],
                    )

                    print("  Relevant Python files:")

                    if python_matches:
                        for match in python_matches:
                            print(
                                f"    - {match['path']} "
                                f"(score: {match['score']})"
                            )
                            for reason in match["reasons"]:
                                print(f"      Why: {reason}")
                    else:
                        print("    No relevant Python files found.")

                    print("  Relevant documentation files:")

                    if doc_matches:
                        for match in doc_matches:
                            print(
                                f"    - {match['path']} "
                                f"(score: {match['score']})"
                            )
                            for reason in match["reasons"]:
                                print(f"      Why: {reason}")
                    else:
                        print(
                            "    No relevant documentation files "
                            "found with enough evidence."
                        )
            else:
                if issue_status == "failed":
                    pass
                elif issue_status == "budget_exhausted":
                    print(
                        "  No issues were found before scan stopped."
                    )
                else:
                    print("  No matching open issues found.")

            if discovered_files:
                print("\nPython files:")
                for path in discovered_files[:10]:
                    print(f"  {path}")

                if len(discovered_files) > 10:
                    print(
                        f"  ... and {len(discovered_files) - 10} more"
                    )

            if parse_errors:
                print("\nFiles with parse errors:")
                for info in parse_errors:
                    print(f"  {info.path}: {info.parse_error}")

    except EXPECTED_ERRORS as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if issue_failure:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
