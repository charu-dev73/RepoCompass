
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
            snapshot = load_repository(repo_url, Path(tmp))

            discovered_files = snapshot.discovery.python_files
            skipped = snapshot.discovery.skipped_dirs
            parsed_files = snapshot.files

            main_guards = [
                info for info in parsed_files if info.has_main_guard
            ]
            parse_errors = [
                info for info in parsed_files if info.parse_error is not None
            ]

            print(f"\nAnalysed: {snapshot.owner}/{snapshot.repo}")
            print(f"Python files discovered: {len(discovered_files)}")
            print(f"Python files parsed: {len(parsed_files)}")
            print(f"Files with main guard: {len(main_guards)}")
            print(f"Files with parse errors: {len(parse_errors)}")
            print(f"Skipped directories: {len(skipped)}")
            print(f"Dependency graph nodes: {len(snapshot.graph.nodes())}")
            print(f"Dependency graph edges: {len(snapshot.graph.edges())}")

            if snapshot.entrypoints:
                print("\nDetected entry points:")
                for path in snapshot.entrypoints:
                    print(f"  - {path}")
            else:
                print("\nNo likely entry points detected.")

            if snapshot.reading_path:
                print("\nSuggested reading path:")
                for step in snapshot.reading_path:
                    print(f"  {step.order}. {step.path}")
                    print(f"     Why: {step.reason}")
            else:
                print("\nNo reading path could be generated.")

            if discovered_files:
                print("\nPython files:")
                for path in discovered_files[:10]:
                    print(f"  {path}")

                if len(discovered_files) > 10:
                    print(f"  ... and {len(discovered_files) - 10} more")

            if parse_errors:
                print("\nFiles with parse errors:")
                for info in parse_errors:
                    print(f"  {info.path}: {info.parse_error}")

    except EXPECTED_ERRORS as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
