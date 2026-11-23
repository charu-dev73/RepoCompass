import io
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlencode

import pytest

from api import _resolve_serve_address, app, create_app, serve
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
    assert payload["issue_discovery"]["status"] == "failed"
    assert payload["issue_discovery"]["complete"] is False
    assert payload["issue_discovery"]["issues_found"] == 1
    assert payload["issue_discovery"]["scanned_items"] == 30
    assert payload["issue_discovery"]["pages_fetched"] == 1
    assert payload["issue_discovery"]["warnings"] == [
        "Could not fetch contribution issues"
    ]
    assert payload["issue_discovery"]["error"] == {
        "type": "GitHubAPIError",
        "message": "Contribution issue discovery failed",
        "status_code": 500,
        "retry_after": None,
        "rate_limit_reset": None,
    }


def test_analyze_reports_budget_exhausted_issue_discovery():
    snapshot = make_snapshot()
    snapshot.issue_discovery = {
        "status": "budget_exhausted",
        "complete": False,
        "issues_found": 1,
        "scanned_items": 300,
        "pages_fetched": 3,
        "warnings": [
            "contribution issue scan stopped after 300 items "
            "because the scan budget (300) was exhausted"
        ],
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
    assert invalid_payload == {"error": "Invalid GitHub repository URL"}


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
    assert payload == {"error": "Repository not found or not public"}


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
    assert upstream_payload == {"error": "Upstream GitHub request failed"}
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
            raise RepositoryTooLarge(
                "Repository /private/tmp/repocompass exceeds size limit"
            )
        if url.endswith("/invalid"):
            raise InvalidArchiveError(
                "Downloaded file is not a valid ZIP archive: "
                "/tmp/repocompass-api-abc/repo.zip"
            )
        raise UnsafeArchiveError(
            "Extraction would follow an existing symbolic link: "
            "/tmp/repocompass-api-abc/extracted/project"
        )

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
    assert too_large_payload == {"error": "Repository is too large to analyze"}
    assert invalid_status == 422
    assert invalid_payload == {
        "error": "Repository archive is invalid or unsafe"
    }
    assert unsafe_status == 422
    assert unsafe_payload == {
        "error": "Repository archive is invalid or unsafe"
    }
    assert "repocompass" not in str(too_large_payload)
    assert "/tmp" not in str(invalid_payload)
    assert "/tmp" not in str(unsafe_payload)


def test_analyze_sanitizes_failed_issue_discovery_payload():
    snapshot = make_snapshot()
    snapshot.issue_discovery = {
        "status": "failed",
        "complete": False,
        "issues_found": 1,
        "scanned_items": 30,
        "pages_fetched": 1,
        "warnings": [
            "could not fetch contribution issues: "
            "Could not reach GitHub: /tmp/socket-trace",
            "partial results preserved",
        ],
        "error": {
            "type": "GitHubAPIError",
            "message": "Could not reach GitHub: "
            "httpx.ConnectError('/private/tmp/proxy')",
            "status_code": None,
            "retry_after": "60",
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
    assert payload["owner"] == "example"
    assert payload["repo"] == "repo"
    assert payload["contribution_issues"] == snapshot.contribution_issues
    assert payload["issue_discovery"]["status"] == "failed"
    assert payload["issue_discovery"]["complete"] is False
    assert payload["issue_discovery"]["issues_found"] == 1
    assert payload["issue_discovery"]["scanned_items"] == 30
    assert payload["issue_discovery"]["pages_fetched"] == 1
    assert payload["issue_discovery"]["warnings"] == [
        "Could not fetch contribution issues"
    ]
    assert payload["issue_discovery"]["error"]["type"] == "GitHubAPIError"
    assert payload["issue_discovery"]["error"]["message"] == (
        "Contribution issue discovery failed"
    )
    assert payload["issue_discovery"]["error"]["retry_after"] == "60"
    assert "/tmp" not in json.dumps(payload)
    assert "httpx" not in json.dumps(payload)


def test_analyze_sanitizes_failed_issue_discovery_malformed_variants():
    sensitive = "/tmp/socket-trace httpx.ConnectError('/private/tmp/proxy')"
    cases = [
        {
            "issue_discovery": {
                "status": "failed",
                "complete": False,
                "issues_found": 2,
                "scanned_items": 12,
                "pages_fetched": 1,
                "warnings": ["partial results preserved"],
                "error": sensitive,
            },
            "expected_error": {
                "type": "IssueDiscoveryError",
                "message": "Contribution issue discovery failed",
                "status_code": None,
                "retry_after": None,
                "rate_limit_reset": None,
            },
            "expected_warnings": ["Could not fetch contribution issues"],
        },
        {
            "issue_discovery": {
                "status": "failed",
                "complete": False,
                "issues_found": 1,
                "scanned_items": 9,
                "pages_fetched": 1,
                "error": {
                    "type": "GitHubAPIError",
                    "message": sensitive,
                    "status_code": 502,
                },
            },
            "expected_error": {
                "type": "GitHubAPIError",
                "message": "Contribution issue discovery failed",
                "status_code": 502,
                "retry_after": None,
                "rate_limit_reset": None,
            },
            "expected_warnings": ["Could not fetch contribution issues"],
        },
        {
            "issue_discovery": {
                "status": "failed",
                "complete": False,
                "issues_found": 1,
                "scanned_items": 9,
                "pages_fetched": 1,
                "warnings": "trace at /tmp/socket-trace",
                "error": None,
            },
            "expected_error": {
                "type": "IssueDiscoveryError",
                "message": "Contribution issue discovery failed",
                "status_code": None,
                "retry_after": None,
                "rate_limit_reset": None,
            },
            "expected_warnings": ["Could not fetch contribution issues"],
        },
        {
            "issue_discovery": {
                "status": "failed",
                "complete": False,
                "issues_found": 1,
                "scanned_items": 9,
                "pages_fetched": 1,
                "warnings": [
                    {
                        "detail": "httpx.ConnectError",
                        "path": "/tmp/socket-trace",
                    },
                    7,
                ],
                "error": {"message": sensitive},
            },
            "expected_error": {
                "type": "IssueDiscoveryError",
                "message": "Contribution issue discovery failed",
                "status_code": None,
                "retry_after": None,
                "rate_limit_reset": None,
            },
            "expected_warnings": ["Could not fetch contribution issues"],
        },
        {
            "issue_discovery": {
                "status": "failed",
                "complete": False,
                "issues_found": 1,
                "scanned_items": 9,
                "pages_fetched": 1,
                "warnings": [
                    "upstream trace: httpx.ConnectError('/tmp/socket')",
                    "Could not reach GitHub: /private/tmp/proxy",
                ],
                "error": {
                    "type": "GitHubAPIError",
                    "message": sensitive,
                },
            },
            "expected_error": {
                "type": "GitHubAPIError",
                "message": "Contribution issue discovery failed",
                "status_code": None,
                "retry_after": None,
                "rate_limit_reset": None,
            },
            "expected_warnings": ["Could not fetch contribution issues"],
        },
    ]

    for case in cases:
        snapshot = make_snapshot()
        snapshot.issue_discovery = case["issue_discovery"]

        app = create_app(
            analyzer=lambda url, workdir, fetch_issues, snapshot=snapshot: snapshot
        )
        status, _, payload = call_api(
            app,
            "/analyze",
            {"url": "https://github.com/example/repo"},
        )

        assert status == 502
        assert payload["owner"] == "example"
        assert payload["repo"] == "repo"
        assert payload["contribution_issues"] == snapshot.contribution_issues
        assert payload["issue_discovery"]["status"] == "failed"
        assert payload["issue_discovery"]["complete"] is False
        assert payload["issue_discovery"]["issues_found"] == case[
            "issue_discovery"
        ]["issues_found"]
        assert payload["issue_discovery"]["scanned_items"] == case[
            "issue_discovery"
        ]["scanned_items"]
        assert payload["issue_discovery"]["pages_fetched"] == case[
            "issue_discovery"
        ]["pages_fetched"]
        assert payload["issue_discovery"]["error"] == case["expected_error"]
        assert payload["issue_discovery"]["warnings"] == case[
            "expected_warnings"
        ]

        serialized = json.dumps(payload)
        assert "/tmp" not in serialized
        assert "/private/tmp" not in serialized
        assert "httpx" not in serialized
        assert "socket-trace" not in serialized
        assert "ConnectError" not in serialized


def test_analyze_sanitizes_non_dictionary_issue_discovery():
    snapshot = make_snapshot()
    snapshot.issue_discovery = "could not fetch: /tmp/socket-trace httpx"

    app = create_app(analyzer=lambda url, workdir, fetch_issues: snapshot)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 502
    assert payload["owner"] == "example"
    assert payload["repo"] == "repo"
    assert payload["issue_discovery"] == {
        "status": "failed",
        "complete": False,
        "issues_found": 0,
        "scanned_items": 0,
        "pages_fetched": 0,
        "warnings": ["Could not fetch contribution issues"],
        "error": {
            "type": "IssueDiscoveryError",
            "message": "Contribution issue discovery failed",
            "status_code": None,
            "retry_after": None,
            "rate_limit_reset": None,
        },
    }

    serialized = json.dumps(payload)
    assert "/tmp" not in serialized
    assert "httpx" not in serialized
    assert "socket-trace" not in serialized


def test_analyze_sanitizes_issue_discovery_warning_and_error_strictly():
    sensitive = "httpx.ConnectError('/tmp/socket-trace')"
    snapshot = make_snapshot()
    snapshot.issue_discovery = {
        "status": "failed",
        "complete": False,
        "issues_found": 1,
        "scanned_items": 30,
        "pages_fetched": 1,
        "warnings": [
            "contribution candidate scan for label "
            f"'{sensitive}' stopped after 10 items while more "
            "candidates were available",
            "contribution issue scan stopped after 30 "
            f"{sensitive} items because the scan budget (300) "
            "was exhausted",
            "contribution issue scan stopped after 30 items "
            "because the scan budget (300) was exhausted",
            "contribution candidate scan for mixed title fallback "
            "stopped after 5 items while more candidates were "
            "available",
        ],
        "error": {
            "type": f"httpx.ConnectError('{sensitive}')",
            "message": sensitive,
            "status_code": 502,
            "retry_after": "60",
            "rate_limit_reset": "/tmp/reset",
        },
    }

    app = create_app(analyzer=lambda url, workdir, fetch_issues: snapshot)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 502
    assert payload["issue_discovery"]["status"] == "failed"
    assert payload["issue_discovery"]["complete"] is False
    assert payload["issue_discovery"]["issues_found"] == 1
    assert payload["issue_discovery"]["scanned_items"] == 30
    assert payload["issue_discovery"]["pages_fetched"] == 1
    assert payload["issue_discovery"]["warnings"] == [
        "contribution issue scan stopped after 30 items "
        "because the scan budget (300) was exhausted",
        "contribution candidate scan for mixed title fallback "
        "stopped after 5 items while more candidates were "
        "available",
    ]
    assert payload["issue_discovery"]["error"] == {
        "type": "IssueDiscoveryError",
        "message": "Contribution issue discovery failed",
        "status_code": 502,
        "retry_after": "60",
        "rate_limit_reset": None,
    }

    serialized = json.dumps(payload)
    assert "httpx" not in serialized
    assert "/tmp" not in serialized
    assert "/private/tmp" not in serialized
    assert "socket-trace" not in serialized
    assert "ConnectError" not in serialized


def test_analyze_sanitizes_issue_discovery_metadata_fields():
    diagnostic = "httpx.ConnectError"

    cases = [
        {
            "error": {
                "type": "GitHubAPIError",
                "message": diagnostic,
                "status_code": diagnostic,
                "retry_after": "120",
                "rate_limit_reset": "1712345678",
            },
            "expected": {
                "type": "GitHubAPIError",
                "message": "Contribution issue discovery failed",
                "status_code": None,
                "retry_after": "120",
                "rate_limit_reset": "1712345678",
            },
        },
        {
            "error": {
                "type": "GitHubAPIError",
                "message": diagnostic,
                "status_code": 429,
                "retry_after": diagnostic,
                "rate_limit_reset": "1712345678",
            },
            "expected": {
                "type": "GitHubAPIError",
                "message": "Contribution issue discovery failed",
                "status_code": 429,
                "retry_after": None,
                "rate_limit_reset": "1712345678",
            },
        },
        {
            "error": {
                "type": "GitHubAPIError",
                "message": diagnostic,
                "status_code": 429,
                "retry_after": "Wed, 21 Oct 2015 07:28:00 GMT",
                "rate_limit_reset": diagnostic,
            },
            "expected": {
                "type": "GitHubAPIError",
                "message": "Contribution issue discovery failed",
                "status_code": 429,
                "retry_after": "Wed, 21 Oct 2015 07:28:00 GMT",
                "rate_limit_reset": None,
            },
        },
    ]

    for case in cases:
        snapshot = make_snapshot()
        snapshot.issue_discovery = {
            "status": "failed",
            "complete": False,
            "issues_found": 1,
            "scanned_items": 30,
            "pages_fetched": 1,
            "warnings": ["Could not fetch contribution issues"],
            "error": case["error"],
        }

        app = create_app(
            analyzer=lambda url, workdir, fetch_issues, snapshot=snapshot: snapshot
        )
        status, _, payload = call_api(
            app,
            "/analyze",
            {"url": "https://github.com/example/repo"},
        )

        assert status == 502
        assert payload["issue_discovery"]["error"] == case["expected"]

        serialized = json.dumps(payload)
        assert "httpx" not in serialized
        assert "ConnectError" not in serialized
        assert "/tmp" not in serialized
        assert "/private/tmp" not in serialized


def test_analyze_sanitizes_retry_after_and_rate_limit_reset_formats():
    malformed_parseable_date = "Tue, 01 Jan 2019 00:00:00 +0000"
    unicode_digits = "\u0661\u0662\u0663"

    cases = [
        {
            "error": {
                "type": "GitHubAPIError",
                "message": "x",
                "status_code": 429,
                "retry_after": malformed_parseable_date,
                "rate_limit_reset": "1712345678",
            },
            "expected": {
                "type": "GitHubAPIError",
                "message": "Contribution issue discovery failed",
                "status_code": 429,
                "retry_after": None,
                "rate_limit_reset": "1712345678",
            },
        },
        {
            "error": {
                "type": "GitHubAPIError",
                "message": "x",
                "status_code": 429,
                "retry_after": "Wed, 21 Oct 2015 07:28:00 GMT",
                "rate_limit_reset": "1712345678",
            },
            "expected": {
                "type": "GitHubAPIError",
                "message": "Contribution issue discovery failed",
                "status_code": 429,
                "retry_after": "Wed, 21 Oct 2015 07:28:00 GMT",
                "rate_limit_reset": "1712345678",
            },
        },
        {
            "error": {
                "type": "GitHubAPIError",
                "message": "x",
                "status_code": 429,
                "retry_after": "Wed, 2\u0661 Oct 2015 07:28:00 GMT",
                "rate_limit_reset": "1712345678",
            },
            "expected": {
                "type": "GitHubAPIError",
                "message": "Contribution issue discovery failed",
                "status_code": 429,
                "retry_after": None,
                "rate_limit_reset": "1712345678",
            },
        },
        {
            "error": {
                "type": "GitHubAPIError",
                "message": "x",
                "status_code": 429,
                "retry_after": "120",
                "rate_limit_reset": "1712345678",
            },
            "expected": {
                "type": "GitHubAPIError",
                "message": "Contribution issue discovery failed",
                "status_code": 429,
                "retry_after": "120",
                "rate_limit_reset": "1712345678",
            },
        },
        {
            "error": {
                "type": "GitHubAPIError",
                "message": "x",
                "status_code": 429,
                "retry_after": unicode_digits,
                "rate_limit_reset": unicode_digits,
            },
            "expected": {
                "type": "GitHubAPIError",
                "message": "Contribution issue discovery failed",
                "status_code": 429,
                "retry_after": None,
                "rate_limit_reset": None,
            },
        },
    ]

    for case in cases:
        snapshot = make_snapshot()
        snapshot.issue_discovery = {
            "status": "failed",
            "complete": False,
            "issues_found": 1,
            "scanned_items": 30,
            "pages_fetched": 1,
            "warnings": ["Could not fetch contribution issues"],
            "error": case["error"],
        }

        app = create_app(
            analyzer=lambda url, workdir, fetch_issues, snapshot=snapshot: snapshot
        )
        status, _, payload = call_api(
            app,
            "/analyze",
            {"url": "https://github.com/example/repo"},
        )

        assert status == 502
        assert payload["issue_discovery"]["error"] == case["expected"]


def test_analyze_failed_issue_discovery_omits_unexpected_fields():
    snapshot = make_snapshot()
    snapshot.issue_discovery = {
        "status": "failed",
        "complete": False,
        "issues_found": 2,
        "scanned_items": 9,
        "pages_fetched": 1,
        "warnings": ["Could not fetch contribution issues"],
        "error": {
            "type": "GitHubAPIError",
            "message": "Contribution issue discovery failed",
            "status_code": 502,
            "retry_after": "30",
            "rate_limit_reset": "1712345678",
            "token": "ghp_secret",
            "path": "/tmp/secret",
        },
        "internal_path": "/tmp/repocompass-api-abc/repo.zip",
        "debug_trace": "httpx.ConnectError('/private/tmp/proxy')",
        "authorization": "Bearer secret-token",
    }

    app = create_app(analyzer=lambda url, workdir, fetch_issues: snapshot)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 502
    assert payload["issue_discovery"] == {
        "status": "failed",
        "complete": False,
        "issues_found": 2,
        "scanned_items": 9,
        "pages_fetched": 1,
        "warnings": ["Could not fetch contribution issues"],
        "error": {
            "type": "GitHubAPIError",
            "message": "Contribution issue discovery failed",
            "status_code": 502,
            "retry_after": "30",
            "rate_limit_reset": "1712345678",
        },
    }
    serialized = json.dumps(payload)
    assert "/tmp" not in serialized
    assert "/private/tmp" not in serialized
    assert "ghp_secret" not in serialized
    assert "Bearer secret-token" not in serialized
    assert "httpx" not in serialized
    assert "ConnectError" not in serialized


def test_analyze_complete_issue_discovery_omits_unexpected_fields():
    snapshot = make_snapshot()
    snapshot.issue_discovery = {
        "status": "complete",
        "complete": True,
        "issues_found": 1,
        "scanned_items": 30,
        "pages_fetched": 1,
        "warnings": [],
        "error": None,
        "internal_path": "/tmp/repocompass-api-abc/repo.zip",
        "debug_trace": "httpx.ConnectError('/private/tmp/proxy')",
        "authorization": "Bearer secret-token",
    }

    app = create_app(analyzer=lambda url, workdir, fetch_issues: snapshot)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 200
    assert payload["issue_discovery"] == {
        "status": "complete",
        "complete": True,
        "issues_found": 1,
        "scanned_items": 30,
        "pages_fetched": 1,
        "warnings": [],
        "error": None,
    }
    serialized = json.dumps(payload)
    assert "/tmp" not in serialized
    assert "/private/tmp" not in serialized
    assert "Bearer secret-token" not in serialized
    assert "httpx" not in serialized
    assert "ConnectError" not in serialized


def test_analyze_budget_exhausted_issue_discovery_omits_unexpected_fields():
    snapshot = make_snapshot()
    snapshot.issue_discovery = {
        "status": "budget_exhausted",
        "complete": False,
        "issues_found": 1,
        "scanned_items": 300,
        "pages_fetched": 3,
        "warnings": [
            "contribution issue scan stopped after 300 items "
            "because the scan budget (300) was exhausted"
        ],
        "error": None,
        "internal_path": "/tmp/repocompass-api-abc/repo.zip",
        "debug_trace": "httpx.ConnectError('/private/tmp/proxy')",
        "authorization": "Bearer secret-token",
    }

    app = create_app(analyzer=lambda url, workdir, fetch_issues: snapshot)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 200
    assert payload["issue_discovery"] == {
        "status": "budget_exhausted",
        "complete": False,
        "issues_found": 1,
        "scanned_items": 300,
        "pages_fetched": 3,
        "warnings": [
            "contribution issue scan stopped after 300 items "
            "because the scan budget (300) was exhausted"
        ],
        "error": None,
    }
    serialized = json.dumps(payload)
    assert "/tmp" not in serialized
    assert "/private/tmp" not in serialized
    assert "Bearer secret-token" not in serialized
    assert "httpx" not in serialized
    assert "ConnectError" not in serialized


def test_analyze_sanitizes_invalid_issue_discovery_status_and_fields():
    snapshot = make_snapshot()
    snapshot.issue_discovery = {
        "status": "PARTIAL /tmp/secret",
        "complete": "false",
        "issues_found": -1,
        "scanned_items": True,
        "pages_fetched": "3",
        "warnings": [
            "contribution issue scan stopped after 300 items "
            "because the scan budget (300) was exhausted",
            "httpx.ConnectError('/tmp/secret')",
            {"path": "/tmp/secret"},
        ],
        "error": {
            "type": "GitHubAPIError",
            "message": "httpx.ConnectError('/tmp/secret')",
            "status_code": 500,
            "retry_after": "30",
            "rate_limit_reset": "1712345678",
            "token": "ghp_secret",
        },
        "internal_path": "/tmp/repocompass-api-abc/repo.zip",
    }

    app = create_app(analyzer=lambda url, workdir, fetch_issues: snapshot)
    status, _, payload = call_api(
        app,
        "/analyze",
        {"url": "https://github.com/example/repo"},
    )

    assert status == 502
    assert payload["issue_discovery"] == {
        "status": "failed",
        "complete": False,
        "issues_found": 0,
        "scanned_items": 0,
        "pages_fetched": 0,
        "warnings": [
            "contribution issue scan stopped after 300 items "
            "because the scan budget (300) was exhausted"
        ],
        "error": {
            "type": "GitHubAPIError",
            "message": "Contribution issue discovery failed",
            "status_code": 500,
            "retry_after": "30",
            "rate_limit_reset": "1712345678",
        },
    }
    serialized = json.dumps(payload)
    assert "/tmp" not in serialized
    assert "/private/tmp" not in serialized
    assert "ghp_secret" not in serialized
    assert "httpx" not in serialized
    assert "ConnectError" not in serialized


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


def test_api_app_wsgi_compatibility():
    status, headers, payload = call_api(app, "/health")

    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert payload == {"status": "ok"}


def test_resolve_serve_address_defaults(monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    assert _resolve_serve_address() == ("127.0.0.1", 8000)
    assert _resolve_serve_address(host="0.0.0.0", port=9000) == (
        "0.0.0.0",
        9000,
    )


def test_resolve_serve_address_uses_env(monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "5050")

    assert _resolve_serve_address() == ("0.0.0.0", 5050)
    assert _resolve_serve_address(port=6000) == ("0.0.0.0", 6000)


@pytest.mark.parametrize(
    "port_value",
    ["abc", "", "-1", "0", "65536", "1.5", True, False],
)
def test_resolve_serve_address_rejects_invalid_port(monkeypatch, port_value):
    monkeypatch.delenv("PORT", raising=False)

    with pytest.raises(ValueError):
        _resolve_serve_address(port=port_value)

    if isinstance(port_value, str):
        monkeypatch.setenv("PORT", port_value)
        with pytest.raises(ValueError):
            _resolve_serve_address()


def test_serve_uses_resolved_defaults(monkeypatch):
    import wsgiref.simple_server

    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    calls = {}

    class DummyServer:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def serve_forever(self):
            calls["served"] = True

    def fake_make_server(host, port, app_obj, **kwargs):
        calls["host"] = host
        calls["port"] = port
        calls["app"] = app_obj
        calls["kwargs"] = kwargs
        return DummyServer()

    monkeypatch.setattr(
        wsgiref.simple_server,
        "make_server",
        fake_make_server,
    )

    serve()

    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8000
    assert calls["app"] is app
    assert calls["served"] is True
    assert calls["kwargs"]["server_class"].__name__ == "ThreadingWSGIServer"


def test_serve_uses_port_env(monkeypatch):
    import wsgiref.simple_server

    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.setenv("PORT", "5050")

    calls = {}

    class DummyServer:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def serve_forever(self):
            calls["served"] = True

    def fake_make_server(host, port, app_obj, **kwargs):
        calls["host"] = host
        calls["port"] = port
        calls["app"] = app_obj
        return DummyServer()

    monkeypatch.setattr(
        wsgiref.simple_server,
        "make_server",
        fake_make_server,
    )

    serve()

    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 5050
    assert calls["app"] is app
    assert calls["served"] is True
