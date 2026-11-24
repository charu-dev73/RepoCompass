# RepoCompass

**Understand unfamiliar Python repositories. Find your way through the code. Discover contribution opportunities.**

RepoCompass is a Python CLI and WSGI API for exploring unfamiliar public GitHub Python repositories. It helps developers and new contributors get oriented by analyzing repository structure and surfacing where to start reading and contributing.

## Quick try

```bash
git clone https://github.com/charu-dev73/RepoCompass.git
cd RepoCompass
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python cli.py https://github.com/psf/requests
```

## Sample output

Excerpt from a previous analysis of `pallets/flask` (not the full CLI output):

```text
Repository: pallets/flask
Python files discovered: 83
Python files parsed: 83
Documentation files discovered: 82
Files with main guard: 1
Files with parse errors: 0
Skipped directories: 0
Dependency graph nodes: 83
Dependency graph edges: 176

Detected entry points:
  - src/flask/__main__.py
  - src/flask/cli.py
  - src/flask/app.py
  - src/flask/sansio/app.py

Suggested reading path:
  1. src/flask/__main__.py
  2. src/flask/cli.py
  3. src/flask/app.py
  4. src/flask/sansio/app.py
  5. src/flask/__init__.py
  6. src/flask/globals.py
  7. src/flask/helpers.py
  8. src/flask/ctx.py

Beginner-friendly contribution issues:
  No matching open issues found.
```

## Core capabilities

- **Repository discovery** - Fetches a GitHub repository archive and discovers Python source and documentation files.
- **Python analysis** - Parses Python files and extracts import relationships.
- **Dependency graph** - Builds a module dependency graph from resolved imports.
- **Entry-point detection** - Identifies likely primary and secondary entry points.
- **Guided reading path** - Suggests an ordered list of files to read, with reasons.
- **Contribution discovery** - Finds beginner-friendly open issues and maps them to relevant code and docs.
- **CLI and HTTP API** - Run analyses from the command line or through the `api:app` WSGI application.

## How it works

A repository passes through the following analysis stages:

1. **Fetch:** Retrieve repository metadata and download its source archive from GitHub.
2. **Discover:** Identify Python files and documentation while applying repository safety and size limits.
3. **Parse:** Analyze Python source files and extract import information.
4. **Resolve:** Resolve import relationships between discovered modules.
5. **Build graph:** Construct a dependency graph from the resolved relationships.
6. **Identify entry points:** Detect likely entry points in the repository.
7. **Generate reading path:** Produce an ordered sequence of files to explore.
8. **Discover contributions:** Find suitable open issues and associate them with relevant code and documentation.

## Installation

Clone the repository:

```bash
git clone https://github.com/charu-dev73/RepoCompass.git
cd RepoCompass
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

For development and testing:

```bash
python -m pip install -r requirements-dev.txt
```

## Usage

### Command-line interface

Analyze a public GitHub repository:

```bash
python cli.py https://github.com/psf/requests
```

The CLI reports:

- Repository analysis statistics.
- Discovered and parsed Python files.
- Documentation files.
- Dependency graph nodes and edges.
- Detected entry points.
- Suggested reading path and explanations.
- Beginner-friendly contribution issues.
- Relevant source files and documentation for discovered issues.

The CLI expects exactly one GitHub repository URL.

### GitHub authentication

Set `GITHUB_TOKEN` to use authenticated GitHub API access:

```bash
export GITHUB_TOKEN="your_github_token"
```

Authentication can improve API rate limits and reliability. Keep tokens private and never commit them to the repository.

## Project architecture

The project separates repository analysis into focused modules.

| Module | Responsibility |
|---|---|
| `engine/fetch.py` | GitHub metadata, archive downloads, extraction and safety checks |
| `engine/discover.py` | Source and documentation discovery |
| `engine/parse.py` | Python source and import parsing |
| `engine/resolve.py` | Import and module resolution |
| `engine/graph.py` | Dependency graph construction |
| `engine/entrypoints.py` | Entry-point detection |
| `engine/reading_path.py` | Suggested file reading paths |
| `engine/issues.py` | GitHub issue discovery |
| `engine/issue_mapping.py` | Mapping issues to relevant Python files |
| `engine/doc_issue_mapping.py` | Mapping issues to relevant documentation |
| `engine/pipeline.py` | Coordinates the repository analysis pipeline |

The command-line interface is implemented in `cli.py`, while `api.py` exposes the analysis pipeline through a WSGI application.

## HTTP API

RepoCompass exposes a WSGI application at `api:app`.

### Endpoints

**`GET /health`**

Example response:

```json
{"status": "ok"}
```

**`GET /analyze?url=<github-repo-url>`**

Requires the `url` query parameter containing a public GitHub repository URL.

Example:

```bash
curl --get \
  --data-urlencode "url=https://github.com/psf/requests" \
  http://127.0.0.1:8000/analyze
```

### Local development

Start the built-in threaded WSGI server:

```bash
python -c "from api import serve; serve()"
```

Local defaults:

- Host: `127.0.0.1`
- Port: `8000`

Both can be configured using environment variables:

- `HOST`: Bind host when no explicit host is passed.
- `PORT`: Bind port when no explicit port is passed.

### Production deployment

Use a production WSGI server such as Gunicorn:

```bash
gunicorn --bind 0.0.0.0:$PORT api:app
```

The hosting environment must provide `PORT`.

### Environment variables

| Variable | Description |
|---|---|
| `HOST` | Optional bind host for the development server |
| `PORT` | Optional local server port; generally provided by hosting platforms |
| `GITHUB_TOKEN` | Optional GitHub token for authenticated API requests |

### HTTP status codes

| Status | Meaning |
|---|---|
| `200` | Analysis completed |
| `400` | Invalid or missing URL, or oversized input |
| `404` | Repository or route not found |
| `405` | Unsupported HTTP method |
| `422` | Repository or archive cannot be processed |
| `500` | Internal error or response exceeds configured size limit |
| `502` | Upstream GitHub/fetch error or issue-discovery failure |
| `503` | Analysis capacity unavailable |

### API defaults and limits

| Setting | Default |
|---|---:|
| Concurrent analyses | 2 per process |
| Maximum URL length | 2,048 characters |
| Maximum response size | 5,000,000 bytes |
| Maximum reported repository size | 200 MB |
| Maximum downloaded ZIP size | 50 MB |

## Testing

Run the test suite:

```bash
python -m pytest -p no:cacheprovider -q
```

The tests cover repository fetching and extraction, source discovery, parsing, dependency resolution, graph construction, entry-point detection, reading paths, issue discovery, issue mapping, CLI behavior, and HTTP API behavior.

## Limitations

- Currently focuses on Python repositories.
- Only the repository's default branch is analyzed.
- Repository size is limited to 200 MB as reported by GitHub.
- Downloaded ZIP archives are limited to 50 MB.
- Repositories containing symbolic links are rejected for safety.
- Skipped directories are identified by directory name.
- Unauthenticated GitHub API requests are subject to rate limits.
- Entry-point detection and issue-to-file mapping are heuristic and may not always identify the most relevant files.
- The HTTP API has no end-to-end analysis timeout.
- API concurrency limits are in-memory and apply per process.
- Upstream GitHub failures and rate limits can affect analysis availability.

The built-in `serve()` server is intended for local development. Use a production WSGI server for deployment.

## License

No license file is currently included in this repository.
