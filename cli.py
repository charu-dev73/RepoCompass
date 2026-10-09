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

            print(f"Analysed: {snapshot.owner}/{snapshot.repo}")
            print(f"Python files discovered: {len(discovered_files)}")
            print(f"Python files parsed: {len(parsed_files)}")
            print(f"Files with main guard: {len(main_guards)}")
            print(f"Files with parse errors: {len(parse_errors)}")
            print(f"Skipped directories: {len(skipped)}")

            print("\nPython files:")
            for path in discovered_files[:10]:
                print(f"  {path}")

            if len(discovered_files) > 10:
                print(f"  ... and {len(discovered_files) - 10} more")

            if main_guards:
                print("\nFiles with main guards:")
                for info in main_guards:
                    print(f"  {info.path}")

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
