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

            files = snapshot.discovery.python_files
            skipped = snapshot.discovery.skipped_dirs

            print(f"Analysed: {snapshot.owner}/{snapshot.repo}")
            print(f"Python files: {len(files)}")
            print(f"Skipped directories: {len(skipped)}")

            for path in files[:10]:
                print(f"  {path}")

    except EXPECTED_ERRORS as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())