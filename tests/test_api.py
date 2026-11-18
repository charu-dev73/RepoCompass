import io
import json
from pathlib import Path
import threading
from urllib.parse import urlencode

from api import create_app
from engine.discover import DiscoveryResult
from engine.fetch import (
    GitHubAPIError,
    InvalidArchiveError,
    InvalidGitHubURL,
    RepositoryNotFound,
    RepositoryTooLarge,
    UnsafeArchiveError,
)
from engine.pipeline import RepoSnapshot
from engine.reading_path import ReadingStep


def call_api(app, path, query=None, method="GET"):
    query_string = urlencode(query or {})
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query_string,
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": True,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }

    body = b"".join(app(environ, start_response))
    return (
        int(captured["status"].split()[0]),
        captured["headers"],
        json.loads(body),
    )


def make_snapshot():
    return RepoSnapshot(
        owner="example",
        repo="repo",
        root=Path("."),
        discovery=DiscoveryResult(),
        files=[],
        entrypoints=[Path("src/app.py")],
        secondary_entrypoints=[Path("examples/demo.py")],
        reading_path=[
            ReadingStep(
                path=Path("src/app.py"),
                reason="Detected application entry point",
                order=1,
            )
        ],
        contribution_issues=[
            {
                "number": 42,
                "title": "Fix startup",
                "url": "https://github.com/example/repo/issues/42",
                "labels": ["good first issue"],
            }
        ],
        issue_file_matches={
            42: [
                {
                    "path": "src/app.py",
                    "score": 120,
                    "reasons": ["Issue explicitly mentions this file"],
                }
            ]
        },
        issue_doc_matches={
            42: [
                {
                    "path": Path("docs/startup.md"),
                    "score": 25,
                    "reasons": ["Issue title term 'startup' appears"],
                }
            ]
        },
        issue_discovery={
            "status": "complete",
            "complete": True,
            "issues_found": 1,
            "scanned_items": 30,
            "pages_fetched": 1,
            "warnings": [],
            "error": None,
        },
    )


def test_health_endpoint():
    def must_not_analyze(*args, **kwargs):
        raise AssertionError("health must not run repository analysis")

    app = create_app(analyzer=must_not_analyze)
    status, headers, payload = call_api(app, "/health")

    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert payload == {"status": "ok"}


def test_analyze_returns_pipeline_results():
    calls = []
    snapshot = make_snapshot()

    def fake_analyzer(url, workdir, fetch_issues=False):
        calls.append((url, workdir, fetch_issues))
        assert Path(workdir).is_dir()
        return snapshot

    app = create_app(analyzer=fake_analyzer)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 200
    assert calls == [
        (
            "https://github.com/example/repo",
            calls[0][1],
            True,
        )
    ]
    assert payload["owner"] == "example"
    assert payload["repo"] == "repo"
    assert payload["entrypoints"] == ["src/app.py"]
    assert payload["secondary_entrypoints"] == ["examples/demo.py"]
    assert payload["reading_path"] == [
        {
            "path": "src/app.py",
            "reason": "Detected application entry point",
            "order": 1,
        }
    ]
    assert payload["contribution_issues"] == [
        {
            "number": 42,
            "title": "Fix startup",
            "url": "https://github.com/example/repo/issues/42",
            "labels": ["good first issue"],
        }
    ]
    assert payload["issue_file_matches"] == {
        "42": [
            {
                "path": "src/app.py",
                "score": 120,
                "reasons": ["Issue explicitly mentions this file"],
            }
        ]
    }
    assert payload["issue_doc_matches"] == {
        "42": [
            {
                "path": "docs/startup.md",
                "score": 25,
                "reasons": ["Issue title term 'startup' appears"],
            }
        ]
    }
    assert payload["issue_discovery"] == {
        "status": "complete",
        "complete": True,
        "issues_found": 1,
        "scanned_items": 30,
        "pages_fetched": 1,
        "warnings": [],
        "error": None,
    }


def test_analyze_reports_incomplete_issue_discovery():
    snapshot = make_snapshot()
    snapshot.issue_discovery = {
        "status": "failed",
        "complete": False,
        "issues_found": 1,
        "scanned_items": 30,
        "pages_fetched": 1,
        "warnings": ["could not fetch contribution issues: HTTP 500"],
        "error": {
            "type": "GitHubAPIError",
            "message": "HTTP 500",
            "status_code": 500,
            "retry_after": None,
            "rate_limit_reset": None,
        },
    }

    app = create_app(analyzer=lambda url, workdir, fetch_issues: snapshot)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 502
    assert payload["contribution_issues"] == [
        {
            "number": 42,
            "title": "Fix startup",
            "url": "https://github.com/example/repo/issues/42",
            "labels": ["good first issue"],
        }
    ]
    assert payload["issue_discovery"] == snapshot.issue_discovery


def test_analyze_reports_budget_exhausted_issue_discovery():
    snapshot = make_snapshot()
    snapshot.issue_discovery = {
        "status": "budget_exhausted",
        "complete": False,
        "issues_found": 1,
        "scanned_items": 300,
        "pages_fetched": 3,
        "warnings": ["scan budget exhausted"],
        "error": None,
    }

    app = create_app(analyzer=lambda url, workdir, fetch_issues: snapshot)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 200
    assert payload["issue_discovery"] == snapshot.issue_discovery
    assert payload["issue_discovery"]["complete"] is False


def test_analyze_with_issues_disabled_exposes_missing_status():
    snapshot = make_snapshot()
    snapshot.contribution_issues = []
    snapshot.issue_file_matches = {}
    snapshot.issue_doc_matches = {}
    snapshot.issue_discovery = None
    calls = []

    def analyzer(url, workdir, fetch_issues=False):
        calls.append(fetch_issues)
        return snapshot

    app = create_app(analyzer=analyzer, fetch_issues=False)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 200
    assert calls == [False]
    assert payload["issue_discovery"] is None
    assert payload["contribution_issues"] == []


def test_analyze_rejects_invalid_url():
    def invalid_analyzer(url, workdir, fetch_issues=False):
        raise InvalidGitHubURL("Not a github.com URL")

    app = create_app(analyzer=invalid_analyzer)

    missing_status, _, missing_payload = call_api(app, "/analyze")
    invalid_status, _, invalid_payload = call_api(
        app,
        "/analyze",
        {"url": "https://gitlab.com/example/repo"},
    )

    assert missing_status == 400
    assert missing_payload == {
        "error": "Missing required query parameter: url"
    }
    assert invalid_status == 400
    assert invalid_payload == {"error": "Not a github.com URL"}


def test_analyze_returns_not_found_for_missing_repository():
    def missing_analyzer(url, workdir, fetch_issues=False):
        raise RepositoryNotFound(
            "example/repo not found, or it is not public"
        )

    app = create_app(analyzer=missing_analyzer)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 404
    assert payload == {
        "error": "example/repo not found, or it is not public"
    }


def test_analyze_maps_upstream_and_internal_errors():
    def failing_analyzer(url, workdir, fetch_issues=False):
        if url.endswith("/upstream"):
            raise GitHubAPIError("GitHub API unavailable")

        raise RuntimeError("unexpected failure")

    app = create_app(analyzer=failing_analyzer)

    upstream_status, _, upstream_payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/upstream"},
    )
    internal_status, _, internal_payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/internal"},
    )

    assert upstream_status == 502
    assert upstream_payload == {"error": "GitHub API unavailable"}
    assert internal_status == 500
    assert internal_payload == {"error": "Internal server error"}


def test_analyze_limits_concurrent_analyses_to_two():
    snapshot = make_snapshot()
    release = threading.Event()
    both_started = threading.Event()
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def slow_analyzer(url, workdir, fetch_issues=False):
        nonlocal active, maximum_active

        with lock:
            active += 1
            maximum_active = max(maximum_active, active)

            if active == 2:
                both_started.set()

        try:
            if not release.wait(timeout=3):
                raise AssertionError("timed out waiting to release analysis")

            return snapshot
        finally:
            with lock:
                active -= 1

    app = create_app(analyzer=slow_analyzer)
    results = {}
    def run_analysis(index):
        results[index] = call_api(
            app,
            "/analyze",
            {"url": "https://github.com/example/repo"},
        )

    threads = [
        threading.Thread(target=run_analysis, args=(index,))
        for index in range(2)
    ]

    for thread in threads:
        thread.start()

    assert both_started.wait(timeout=3)
    busy_status, busy_headers, busy_payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert busy_status == 503
    assert busy_headers["Retry-After"] == "1"
    assert busy_payload == {
        "error": "Repository analysis capacity reached"
    }

    release.set()

    for thread in threads:
        thread.join(timeout=3)

    assert not any(thread.is_alive() for thread in threads)
    assert [results[index][0] for index in range(2)] == [200, 200]
    assert maximum_active == 2


def test_analyze_maps_archive_and_size_errors():
    def analyzer(url, workdir, fetch_issues=False):
        if url.endswith("/too-large"):
            raise RepositoryTooLarge("Repository exceeds size limit")
        if url.endswith("/invalid"):
            raise InvalidArchiveError("Downloaded file is not a valid ZIP archive")
        raise UnsafeArchiveError("Archive contains unsafe paths")

    app = create_app(analyzer=analyzer)

    too_large_status, _, too_large_payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/too-large"},
    )
    invalid_status, _, invalid_payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/invalid"},
    )
    unsafe_status, _, unsafe_payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/unsafe"},
    )

    assert too_large_status == 422
    assert too_large_payload == {"error": "Repository exceeds size limit"}
    assert invalid_status == 422
    assert invalid_payload == {
        "error": "Downloaded file is not a valid ZIP archive"
    }
    assert unsafe_status == 422
    assert unsafe_payload == {"error": "Archive contains unsafe paths"}


def test_routes_and_methods():
    def must_not_analyze(*args, **kwargs):
        raise AssertionError("handler should not run analysis")

    app = create_app(analyzer=must_not_analyze)

    missing_status, _, missing_payload = call_api(app, "/missing")
    health_status, health_headers, health_payload = call_api(
        app, "/health", method="POST"
    )
    analyze_status, analyze_headers, analyze_payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
        method="POST",
    )

    assert missing_status == 404
    assert missing_payload == {"error": "Not found"}
    assert health_status == 405
    assert health_headers["Allow"] == "GET"
    assert health_payload == {"error": "Method not allowed"}
    assert analyze_status == 405
    assert analyze_headers["Allow"] == "GET"
    assert analyze_payload == {"error": "Method not allowed"}


def test_analyze_rejects_oversized_input():
    called = False

    def analyzer(*args, **kwargs):
        nonlocal called
        called = True
        return make_snapshot()

    app = create_app(analyzer=analyzer, max_url_length=80)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/" + "a" * 100},
    )

    assert status == 400
    assert payload == {"error": "Request URL or query input too long"}
    assert called is False


def test_analyze_rejects_oversized_query_string():
    called = False

    def analyzer(*args, **kwargs):
        nonlocal called
        called = True
        return make_snapshot()

    app = create_app(analyzer=analyzer, max_url_length=40)
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/analyze",
        "QUERY_STRING": "url=https://github.com/example/repo&padding=" + ("a" * 100),
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": True,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }

    body = b"".join(app(environ, start_response))

    assert int(captured["status"].split()[0]) == 400
    assert json.loads(body) == {
        "error": "Request URL or query input too long"
    }
    assert called is False


def test_analyze_rejects_oversized_response_returns_valid_error():
    snapshot = make_snapshot()
    snapshot.contribution_issues = [
        {
            "number": index,
            "title": "title " + ("x" * 120),
            "url": "https://github.com/example/repo/issues/" + str(index),
            "labels": ["good first issue", "y" * 80],
        }
        for index in range(1, 120)
    ]

    app = create_app(
        analyzer=lambda *args, **kwargs: snapshot,
        max_response_bytes=1024,
    )
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 500
    assert payload == {"error": "Response too large"}


def test_create_app_rejects_max_response_bytes_smaller_than_fallback():
    min_bytes = len(
        json.dumps(
            {"error": "Response too large"},
            ensure_ascii=False,
        ).encode("utf-8")
    )
    try:
        create_app(max_response_bytes=min_bytes - 1)
    except ValueError as exc:
        assert str(min_bytes) in str(exc)
    else:
        raise AssertionError(
            "create_app should reject max_response_bytes below fallback size"
        )

    app = create_app(
        analyzer=lambda *args, **kwargs: make_snapshot(),
        max_response_bytes=min_bytes,
    )
    status, _, payload = call_api(app, "/health")
    assert status == 200
    assert payload == {"status": "ok"}


def test_response_size_limit_applies_to_error_responses_and_releases_slot():
    min_bytes = len(
        json.dumps(
            {"error": "Response too large"},
            ensure_ascii=False,
        ).encode("utf-8")
    )

    def analyzer(*args, **kwargs):
        raise GitHubAPIError("x" * 200)

    app = create_app(analyzer=analyzer, max_response_bytes=min_bytes)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 500
    assert payload == {"error": "Response too large"}

    # slot must be released even when response generation hit size fallback
    status, _, payload = call_api(app, "/health")
    assert status == 200
    assert payload == {"status": "ok"}
