# RepoCompass

## HTTP API

RepoCompass exposes a WSGI application at `api:app` for HTTP analysis requests.

### Endpoints

- `GET /health`
  - Example response: `{"status": "ok"}`
- `GET /analyze?url=<github-repo-url>`
  - Requires the `url` query parameter (public GitHub repository URL).

Example:

```bash
curl "http://127.0.0.1:8000/analyze?url=https://github.com/psf/requests"
```

### Local development

Install runtime dependencies:

```bash
python -m pip install -r requirements.txt
```

For development and tests:

```bash
python -m pip install -r requirements-dev.txt
```

Start the built-in threaded WSGI server:

```bash
python -c "from api import serve; serve()"
```

Local defaults (when not overridden): host `127.0.0.1`, port `8000`.

`serve()` also supports environment-based configuration:

- `HOST` (optional): bind host when `host` is not passed explicitly (default: `127.0.0.1`)
- `PORT` (optional): bind port when `port` is not passed explicitly (default: `8000`)

### Production

Use a production WSGI server with the module-level callable `api:app`.

Example (Gunicorn):

```bash
gunicorn --bind 0.0.0.0:$PORT api:app
```

`$PORT` is the HTTP port provided by the hosting platform and must be set in that environment.

### Environment variables

- `PORT` (required by most hosting platforms for production): port to bind the HTTP server to.
- `HOST` (optional): host interface for `serve()` local/dev server (default: `127.0.0.1`). For production Gunicorn deployments, set the bind address explicitly (for example `0.0.0.0:$PORT`).
- `GITHUB_TOKEN` (optional): GitHub token used for repository metadata, archive download, and issue-discovery requests; can improve reliability/rate limits for upstream GitHub access.

### Status codes

- `200`: analysis completed (JSON snapshot payload)
- `400`: bad request (missing/invalid `url` or oversized input)
- `404`: repository or route not found
- `405`: method not allowed (`Allow: GET`)
- `422`: repository/archive cannot be processed (for example too large or unsafe/invalid archive)
- `500`: internal server error, or generated response exceeds the configured size limit (`{"error":"Response too large"}`)
- `502`: upstream GitHub/fetch error, or issue discovery failed during analysis (sanitized snapshot/error payload returned)
- `503`: analysis capacity unavailable (`{"error":"Repository analysis capacity reached"}`, `Retry-After: 1`)

### Defaults and limits

- Default concurrency: `2` concurrent analyses (`max_concurrent_analyses`)
- Default URL/query input limit: `2048` characters (`max_url_length`)
- Default response size limit: `5,000,000` bytes (`max_response_bytes`)

### Operational caveats

- No end-to-end analysis timeout.
- Concurrency limits are per process (in-memory admission control).
- Analyses perform live GitHub requests (metadata/archive/issues); upstream rate limiting or transient failures may return sanitized `502` responses.
- The built-in `serve()` server is intended for local development; use a production WSGI server (for example Gunicorn) for deployed environments.
