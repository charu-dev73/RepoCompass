"""HTTP API for RepoCompass repository analysis."""

from dataclasses import asdict, is_dataclass
from email.utils import parsedate_to_datetime
import json
from http import HTTPStatus
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Callable
from urllib.parse import parse_qs

from engine.fetch import (
    GitHubAPIError,
    InvalidArchiveError,
    InvalidGitHubURL,
    RepositoryNotFound,
    RepositoryTooLarge,
    UnsafeArchiveError,
)
from engine.pipeline import RepoSnapshot, load_repository


Analyzer = Callable[..., RepoSnapshot]


_RESPONSE_TOO_LARGE_PAYLOAD = {"error": "Response too large"}


def _response_too_large_body() -> bytes:
    return json.dumps(
        _RESPONSE_TOO_LARGE_PAYLOAD,
        ensure_ascii=False,
    ).encode("utf-8")


_MIN_RESPONSE_BYTES = len(_response_too_large_body())


def _jsonable(value: Any) -> Any:
    """Convert pipeline values into JSON-compatible structures."""
    if isinstance(value, Path):
        return str(value)

    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))

    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]

    return value


def _status_line(status: HTTPStatus) -> str:
    return f"{status.value} {status.phrase}"


class _ResponseTooLargeError(Exception):
    """Raised when serialized JSON exceeds the configured response limit."""


def _bounded_json_bytes(payload: Any, max_body_bytes: int) -> bytes:
    # Materializes a JSON-compatible copy, then streams encoded chunks and stops
    # once the configured byte limit is exceeded.
    data = _jsonable(payload)
    encoder = json.JSONEncoder(ensure_ascii=False)
    chunks = bytearray()

    for chunk in encoder.iterencode(data):
        encoded = chunk.encode("utf-8")
        if len(chunks) + len(encoded) > max_body_bytes:
            raise _ResponseTooLargeError()
        chunks.extend(encoded)

    return bytes(chunks)


def _json_response(
    start_response: Callable,
    status: HTTPStatus,
    payload: Any,
    headers: list[tuple[str, str]] | None = None,
    max_body_bytes: int | None = None,
) -> list[bytes]:
    try:
        if max_body_bytes is None:
            body = json.dumps(
                _jsonable(payload),
                ensure_ascii=False,
            ).encode("utf-8")
        else:
            body = _bounded_json_bytes(payload, max_body_bytes)
    except _ResponseTooLargeError:
        body = _response_too_large_body()
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        headers = None

    response_headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    response_headers.extend(headers or [])

    start_response(_status_line(status), response_headers)
    return [body]


def _error_response(
    start_response: Callable,
    status: HTTPStatus,
    message: str,
    headers: list[tuple[str, str]] | None = None,
    max_body_bytes: int | None = None,
) -> list[bytes]:
    return _json_response(
        start_response,
        status,
        {"error": message},
        headers=headers,
        max_body_bytes=max_body_bytes,
    )


_SAFE_FAILURE_WARNING = "Could not fetch contribution issues"
_SAFE_FAILURE_ERROR = {
    "type": "IssueDiscoveryError",
    "message": "Contribution issue discovery failed",
    "status_code": None,
    "retry_after": None,
    "rate_limit_reset": None,
}
_SAFE_ISSUE_DISCOVERY_FAILURE = {
    "status": "failed",
    "complete": False,
    "issues_found": 0,
    "scanned_items": 0,
    "pages_fetched": 0,
    "warnings": [_SAFE_FAILURE_WARNING],
    "error": dict(_SAFE_FAILURE_ERROR),
}

_CANDIDATE_SOURCE_NAMES = frozenset(
    {
        "label 'good first issue'",
        "label 'good-first-issue'",
        "label 'good_first_issue'",
        "label 'beginner'",
        "label 'first timers only'",
        "label 'first-timers-only'",
        "label 'first_timers_only'",
        "label 'help wanted'",
        "label 'help-wanted'",
        "label 'help_wanted'",
        "label 'easy'",
        "mixed title fallback",
    }
)
_KNOWN_ISSUE_DISCOVERY_ERROR_TYPES = frozenset(
    {"GitHubAPIError", "RepositoryNotFound"}
)
_BUDGET_WARNING_RE = re.compile(
    r"^contribution issue scan stopped after (\d+) items "
    r"because the scan budget \((\d+)\) was exhausted$"
)
_SOURCE_WARNING_RE = re.compile(
    r"^contribution candidate scan for (.+) stopped after (\d+) items "
    r"while more candidates were available$"
)
_ASCII_DIGITS_RE = re.compile(r"^[0-9]+$")
_IMF_FIXDATE_RE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), "
    r"[0-9]{2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [0-9]{4} "
    r"[0-9]{2}:[0-9]{2}:[0-9]{2} GMT$"
)
_RFC850_DATE_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
    r"[0-9]{2}-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-[0-9]{2} "
    r"[0-9]{2}:[0-9]{2}:[0-9]{2} GMT$"
)
_ASCTIME_DATE_RE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"(?:[0-9]{2}| [0-9]) [0-9]{2}:[0-9]{2}:[0-9]{2} [0-9]{4}$"
)


def _is_safe_issue_warning(warning: str) -> bool:
    # Preserve only known engine-generated, non-diagnostic warnings.
    if _BUDGET_WARNING_RE.fullmatch(warning) is not None:
        return True

    source_match = _SOURCE_WARNING_RE.fullmatch(warning)
    if source_match is None:
        return False

    return source_match.group(1) in _CANDIDATE_SOURCE_NAMES


def _sanitize_status_code(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if 100 <= value <= 599:
        return value
    return None


def _is_valid_http_date(value: str) -> bool:
    if (
        _IMF_FIXDATE_RE.fullmatch(value) is None
        and _RFC850_DATE_RE.fullmatch(value) is None
        and _ASCTIME_DATE_RE.fullmatch(value) is None
    ):
        return False

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return False

    return parsed is not None


def _sanitize_retry_after(value: Any) -> int | str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        if value >= 0:
            return value
        return None
    if not isinstance(value, str):
        return None
    if _ASCII_DIGITS_RE.fullmatch(value):
        return value
    if _is_valid_http_date(value):
        return value
    return None


def _sanitize_rate_limit_reset(value: Any) -> str | None:
    if isinstance(value, str) and _ASCII_DIGITS_RE.fullmatch(value):
        return value
    return None


def _sanitize_issue_discovery_error(error: Any) -> dict[str, Any]:
    if not isinstance(error, dict):
        return dict(_SAFE_FAILURE_ERROR)

    sanitized_error = dict(_SAFE_FAILURE_ERROR)
    error_type = error.get("type")
    if (
        isinstance(error_type, str)
        and error_type in _KNOWN_ISSUE_DISCOVERY_ERROR_TYPES
    ):
        sanitized_error["type"] = error_type

    sanitized_error["status_code"] = _sanitize_status_code(
        error.get("status_code")
    )
    sanitized_error["retry_after"] = _sanitize_retry_after(
        error.get("retry_after")
    )
    sanitized_error["rate_limit_reset"] = _sanitize_rate_limit_reset(
        error.get("rate_limit_reset")
    )
    return sanitized_error


def _sanitize_issue_discovery_warnings(warnings: Any) -> list[str]:
    if not isinstance(warnings, list):
        return [_SAFE_FAILURE_WARNING]

    sanitized_warnings = []
    for warning in warnings:
        if not isinstance(warning, str):
            continue
        if "/" in warning or "\\" in warning:
            continue
        if "could not fetch contribution issues" in warning.lower():
            continue
        if _is_safe_issue_warning(warning):
            sanitized_warnings.append(warning)

    if not sanitized_warnings:
        return [_SAFE_FAILURE_WARNING]

    return sanitized_warnings


_KNOWN_ISSUE_DISCOVERY_STATUSES = frozenset(
    {"complete", "budget_exhausted", "failed"}
)


def _sanitize_non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    if value < 0:
        return 0
    return value


def _sanitize_issue_discovery_status(value: Any) -> str | None:
    if isinstance(value, str) and value in _KNOWN_ISSUE_DISCOVERY_STATUSES:
        return value
    return None


def _sanitize_issue_discovery_complete(
    value: Any,
    status: str,
) -> bool:
    expected = status == "complete"
    if isinstance(value, bool):
        return value if value == expected else expected
    return expected


def _sanitize_issue_discovery_error_for_status(
    error: Any,
    status: str,
) -> dict[str, Any] | None:
    if status != "failed":
        return None
    return _sanitize_issue_discovery_error(error)


def _sanitize_issue_discovery_warnings_for_status(
    warnings: Any,
    status: str,
) -> list[str]:
    if status == "failed":
        return _sanitize_issue_discovery_warnings(warnings)

    if not isinstance(warnings, list):
        return []

    sanitized_warnings = []
    for warning in warnings:
        if not isinstance(warning, str):
            continue
        if "/" in warning or "\\" in warning:
            continue
        if "could not fetch contribution issues" in warning.lower():
            continue
        if _is_safe_issue_warning(warning):
            sanitized_warnings.append(warning)

    return sanitized_warnings


def _sanitize_issue_discovery(
    issue_discovery: Any,
) -> Any:
    if issue_discovery is None:
        return None

    if not isinstance(issue_discovery, dict):
        return dict(_SAFE_ISSUE_DISCOVERY_FAILURE)

    status = _sanitize_issue_discovery_status(issue_discovery.get("status"))
    if status is None:
        return {
            "status": "failed",
            "complete": False,
            "issues_found": _sanitize_non_negative_int(
                issue_discovery.get("issues_found")
            ),
            "scanned_items": _sanitize_non_negative_int(
                issue_discovery.get("scanned_items")
            ),
            "pages_fetched": _sanitize_non_negative_int(
                issue_discovery.get("pages_fetched")
            ),
            "warnings": _sanitize_issue_discovery_warnings(
                issue_discovery.get("warnings")
            ),
            "error": _sanitize_issue_discovery_error(
                issue_discovery.get("error")
            ),
        }

    return {
        "status": status,
        "complete": _sanitize_issue_discovery_complete(
            issue_discovery.get("complete"),
            status,
        ),
        "issues_found": _sanitize_non_negative_int(
            issue_discovery.get("issues_found")
        ),
        "scanned_items": _sanitize_non_negative_int(
            issue_discovery.get("scanned_items")
        ),
        "pages_fetched": _sanitize_non_negative_int(
            issue_discovery.get("pages_fetched")
        ),
        "warnings": _sanitize_issue_discovery_warnings_for_status(
            issue_discovery.get("warnings"),
            status,
        ),
        "error": _sanitize_issue_discovery_error_for_status(
            issue_discovery.get("error"),
            status,
        ),
    }


def _snapshot_payload(snapshot: RepoSnapshot) -> dict[str, Any]:
    return {
        "owner": snapshot.owner,
        "repo": snapshot.repo,
        "entrypoints": snapshot.entrypoints,
        "secondary_entrypoints": snapshot.secondary_entrypoints,
        "reading_path": snapshot.reading_path,
        "contribution_issues": snapshot.contribution_issues,
        "issue_file_matches": snapshot.issue_file_matches,
        "issue_doc_matches": snapshot.issue_doc_matches,
        "issue_discovery": _sanitize_issue_discovery(
            snapshot.issue_discovery
        ),
    }


class RepoCompassAPI:
    """WSGI application exposing RepoCompass analysis over HTTP."""

    def __init__(
        self,
        analyzer: Analyzer | None = None,
        max_concurrent_analyses: int = 2,
        fetch_issues: bool = True,
        max_url_length: int = 2048,
        max_response_bytes: int = 5_000_000,
    ) -> None:
        if max_concurrent_analyses < 1:
            raise ValueError(
                "max_concurrent_analyses must be at least 1"
            )
        if max_url_length < 1:
            raise ValueError("max_url_length must be at least 1")
        if max_response_bytes < _MIN_RESPONSE_BYTES:
            raise ValueError(
                "max_response_bytes must be at least "
                f"{_MIN_RESPONSE_BYTES} bytes"
            )

        self._analyzer = analyzer
        self._fetch_issues = fetch_issues
        self._max_url_length = max_url_length
        self._max_response_bytes = max_response_bytes
        self._analysis_slots = threading.BoundedSemaphore(
            max_concurrent_analyses
        )

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable,
    ) -> list[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")

        if path == "/health":
            return self._health(method, start_response)

        if path == "/analyze":
            return self._analyze(
                method,
                environ,
                start_response,
            )

        return _error_response(
            start_response,
            HTTPStatus.NOT_FOUND,
            "Not found",
            max_body_bytes=self._max_response_bytes,
        )

    def _health(
        self,
        method: str,
        start_response: Callable,
    ) -> list[bytes]:
        if method != "GET":
            return _error_response(
                start_response,
                HTTPStatus.METHOD_NOT_ALLOWED,
                "Method not allowed",
                headers=[("Allow", "GET")],
                max_body_bytes=self._max_response_bytes,
            )

        return _json_response(
            start_response,
            HTTPStatus.OK,
            {"status": "ok"},
            max_body_bytes=self._max_response_bytes,
        )

    def _analyze(
        self,
        method: str,
        environ: dict[str, Any],
        start_response: Callable,
    ) -> list[bytes]:
        if method != "GET":
            return _error_response(
                start_response,
                HTTPStatus.METHOD_NOT_ALLOWED,
                "Method not allowed",
                headers=[("Allow", "GET")],
                max_body_bytes=self._max_response_bytes,
            )

        query_string = environ.get("QUERY_STRING", "")
        if len(query_string) > self._max_url_length:
            return _error_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                "Request URL or query input too long",
                max_body_bytes=self._max_response_bytes,
            )

        query = parse_qs(
            query_string,
            keep_blank_values=True,
        )
        values = query.get("url", [])
        url = values[0].strip() if values else ""

        if not url:
            return _error_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                "Missing required query parameter: url",
                max_body_bytes=self._max_response_bytes,
            )

        if len(url) > self._max_url_length:
            return _error_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                "Request URL or query input too long",
                max_body_bytes=self._max_response_bytes,
            )

        if not self._analysis_slots.acquire(blocking=False):
            return _error_response(
                start_response,
                HTTPStatus.SERVICE_UNAVAILABLE,
                "Repository analysis capacity reached",
                headers=[("Retry-After", "1")],
                max_body_bytes=self._max_response_bytes,
            )

        try:
            analyzer = self._analyzer or load_repository

            with tempfile.TemporaryDirectory(
                prefix="repocompass-api-"
            ) as temporary_directory:
                snapshot = analyzer(
                    url,
                    Path(temporary_directory),
                    fetch_issues=self._fetch_issues,
                )

            payload = _snapshot_payload(snapshot)
            issue_discovery = payload.get("issue_discovery")
            if (
                isinstance(issue_discovery, dict)
                and issue_discovery.get("status") == "failed"
            ):
                return _json_response(
                    start_response,
                    HTTPStatus.BAD_GATEWAY,
                    payload,
                    max_body_bytes=self._max_response_bytes,
                )

            return _json_response(
                start_response,
                HTTPStatus.OK,
                payload,
                max_body_bytes=self._max_response_bytes,
            )

        except InvalidGitHubURL:
            return _error_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                "Invalid GitHub repository URL",
                max_body_bytes=self._max_response_bytes,
            )

        except RepositoryNotFound:
            return _error_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                "Repository not found or not public",
                max_body_bytes=self._max_response_bytes,
            )

        except RepositoryTooLarge:
            return _error_response(
                start_response,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "Repository is too large to analyze",
                max_body_bytes=self._max_response_bytes,
            )

        except (InvalidArchiveError, UnsafeArchiveError):
            return _error_response(
                start_response,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "Repository archive is invalid or unsafe",
                max_body_bytes=self._max_response_bytes,
            )

        except GitHubAPIError:
            return _error_response(
                start_response,
                HTTPStatus.BAD_GATEWAY,
                "Upstream GitHub request failed",
                max_body_bytes=self._max_response_bytes,
            )

        except Exception:
            return _error_response(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Internal server error",
                max_body_bytes=self._max_response_bytes,
            )

        finally:
            self._analysis_slots.release()


def create_app(
    analyzer: Analyzer | None = None,
    max_concurrent_analyses: int = 2,
    fetch_issues: bool = True,
    max_url_length: int = 2048,
    max_response_bytes: int = 5_000_000,
) -> RepoCompassAPI:
    """Create a RepoCompass WSGI application."""
    return RepoCompassAPI(
        analyzer=analyzer,
        max_concurrent_analyses=max_concurrent_analyses,
        fetch_issues=fetch_issues,
        max_url_length=max_url_length,
        max_response_bytes=max_response_bytes,
    )


app = create_app()


def _resolve_serve_address(
    host: str | None = None,
    port: int | str | None = None,
) -> tuple[str, int]:
    """Resolve host/port for serve() using explicit args, env vars, or defaults."""
    resolved_host = (
        host if host is not None else os.environ.get("HOST", "127.0.0.1")
    )

    if port is None:
        port_value: int | str = os.environ.get("PORT", "8000")
    else:
        port_value = port

    if isinstance(port_value, bool):
        raise ValueError("Invalid port: must be an integer between 1 and 65535")

    try:
        resolved_port = int(port_value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid port: {port_value!r}") from None

    if not 1 <= resolved_port <= 65535:
        raise ValueError(
            f"Invalid port: {resolved_port} (must be between 1 and 65535)"
        )

    return resolved_host, resolved_port


def serve(
    host: str | None = None,
    port: int | str | None = None,
) -> None:
    """Run the RepoCompass API with a threaded WSGI server."""
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import (
        WSGIRequestHandler,
        WSGIServer,
        make_server,
    )

    resolved_host, resolved_port = _resolve_serve_address(host, port)

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    with make_server(
        resolved_host,
        resolved_port,
        app,
        server_class=ThreadingWSGIServer,
        handler_class=WSGIRequestHandler,
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    serve()
