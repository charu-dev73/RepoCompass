# RepoCompass

## HTTP API

Start the WSGI server with the existing `serve()` entry point:

```bash
python -c "from api import serve; serve()"
```

By default this serves on `127.0.0.1:8000`.

### Endpoints

- `GET /health`
  - Example response: `{"status": "ok"}`
- `GET /analyze?url=<github-repo-url>`
  - Requires the `url` query parameter (GitHub repository URL).

Example:

```bash
curl "http://127.0.0.1:8000/analyze?url=https://github.com/psf/requests"
```

### Status codes

- `200`: analysis completed (JSON snapshot payload)
- `400`: bad request (missing/invalid `url` or oversized input)
- `404`: repository or route not found
- `422`: repository/archive cannot be processed (for example too large or unsafe/invalid archive)
- `500`: internal server error, or generated response exceeds the configured size limit (`{"error":"Response too large"}`)
- `502`: upstream GitHub/fetch error, or issue discovery failed during analysis (snapshot payload returned)
- `503`: analysis capacity unavailable (`{"error":"Repository analysis capacity reached"}`, `Retry-After: 1`)

### Defaults and limits

- Default concurrency: `2` concurrent analyses (`max_concurrent_analyses`)
- Default URL/query input limit: `2048` characters (`max_url_length`)
- Default response size limit: `5,000,000` bytes (`max_response_bytes`)

### Limitations

- No analysis timeout.
- Concurrency limits are per process.
