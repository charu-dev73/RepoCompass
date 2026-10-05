import sys


def main():
    if len(sys.argv) != 2:
        print("Usage: python cli.py <github-url>")
        return

    repo_url = sys.argv[1]

    print("RepoCompass")
    print(f"Repository: {repo_url}")


if __name__ == "__main__":
    main()