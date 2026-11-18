"""HTTP API for RepoCompass repository analysis."""

from dataclasses import asdict, is_dataclass
import json
from http import HTTPStatus
from pathlib import Path
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
        "issue_discovery": snapshot.issue_discovery,
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

        except InvalidGitHubURL as exc:
            return _error_response(
                start_response,
                HTTPStatus.BAD_REQUEST,
                str(exc),
                max_body_bytes=self._max_response_bytes,
            )

        except RepositoryNotFound as exc:
            return _error_response(
                start_response,
                HTTPStatus.NOT_FOUND,
                str(exc),
                max_body_bytes=self._max_response_bytes,
            )

        except (
            RepositoryTooLarge,
            InvalidArchiveError,
            UnsafeArchiveError,
        ) as exc:
            return _error_response(
                start_response,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                str(exc),
                max_body_bytes=self._max_response_bytes,
            )

        except GitHubAPIError as exc:
            return _error_response(
                start_response,
                HTTPStatus.BAD_GATEWAY,
                str(exc),
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


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the RepoCompass API with a threaded WSGI server."""
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import (
        WSGIRequestHandler,
        WSGIServer,
        make_server,
    )

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    with make_server(
        host,
        port,
        app,
        server_class=ThreadingWSGIServer,
        handler_class=WSGIRequestHandler,
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    serve()
