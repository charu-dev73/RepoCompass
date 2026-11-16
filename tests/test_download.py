import httpx
import pytest

from engine.fetch import (
    GitHubAPIError,
    RepositoryNotFound,
    RepositoryTooLarge,
    download_repo_zip,
)


def test_download_repo_zip_success(monkeypatch, tmp_path):
    def fake_repo_info(owner, repo):
        return {
            "full_name": f"{owner}/{repo}",
            "default_branch": "main",
            "size_kb": 100,
            "language": "Python",
        }

    class FakeStreamResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_bytes(self):
            yield b"hello "
            yield b"world"

    monkeypatch.setattr(
        "engine.fetch.get_repo_info",
        fake_repo_info,
    )
    monkeypatch.setattr(
        "engine.fetch.httpx.stream",
        lambda *args, **kwargs: FakeStreamResponse(),
    )

    result = download_repo_zip(
        "pallets",
        "flask",
        tmp_path,
    )

    assert result == tmp_path / "repo.zip"
    assert result.read_bytes() == b"hello world"


def test_download_repo_zip_cleans_partial_file_on_write_error(
    monkeypatch,
    tmp_path,
):
    def fake_repo_info(owner, repo):
        return {
            "full_name": f"{owner}/{repo}",
            "default_branch": "main",
            "size_kb": 100,
            "language": "Python",
        }

    class FakeStreamResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_bytes(self):
            yield b"partial"

    original_open = open

    class FailingFile:
        def __init__(self, path, mode, *args, **kwargs):
            self._file = original_open(
                path,
                mode,
                *args,
                **kwargs,
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self._file.close()

        def write(self, data):
            raise OSError("disk full")

    def fake_open(*args, **kwargs):
        return FailingFile(*args, **kwargs)

    monkeypatch.setattr(
        "engine.fetch.get_repo_info",
        fake_repo_info,
    )
    monkeypatch.setattr(
        "engine.fetch.httpx.stream",
        lambda *args, **kwargs: FakeStreamResponse(),
    )
    monkeypatch.setattr(
        "engine.fetch.open",
        fake_open,
        raising=False,
    )

    with pytest.raises(OSError, match="disk full"):
        download_repo_zip(
            "pallets",
            "flask",
            tmp_path,
        )

    assert not (tmp_path / "repo.zip").exists()


def test_download_repo_zip_rejects_large_repository(monkeypatch, tmp_path):
    def fake_repo_info(owner, repo):
        return {
            "full_name": f"{owner}/{repo}",
            "default_branch": "main",
            "size_kb": 200_001,
            "language": "Python",
        }

    monkeypatch.setattr(
        "engine.fetch.get_repo_info",
        fake_repo_info,
    )

    with pytest.raises(RepositoryTooLarge):
        download_repo_zip(
            "pallets",
            "flask",
            tmp_path,
        )


def test_download_repo_zip_handles_http_error(monkeypatch, tmp_path):
    def fake_repo_info(owner, repo):
        return {
            "full_name": f"{owner}/{repo}",
            "default_branch": "main",
            "size_kb": 100,
            "language": "Python",
        }

    class FakeStreamResponse:
        status_code = 500

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "engine.fetch.get_repo_info",
        fake_repo_info,
    )
    monkeypatch.setattr(
        "engine.fetch.httpx.stream",
        lambda *args, **kwargs: FakeStreamResponse(),
    )

    with pytest.raises(GitHubAPIError):
        download_repo_zip(
            "pallets",
            "flask",
            tmp_path,
        )


@pytest.mark.parametrize("status_code", [403, 429])
def test_download_repo_zip_handles_rate_limit(
    monkeypatch,
    tmp_path,
    status_code,
):
    def fake_repo_info(owner, repo):
        return {
            "full_name": f"{owner}/{repo}",
            "default_branch": "main",
            "size_kb": 100,
            "language": "Python",
        }

    class FakeStreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    FakeStreamResponse.status_code = status_code

    monkeypatch.setattr(
        "engine.fetch.get_repo_info",
        fake_repo_info,
    )
    monkeypatch.setattr(
        "engine.fetch.httpx.stream",
        lambda *args, **kwargs: FakeStreamResponse(),
    )

    stale_zip = tmp_path / "repo.zip"
    stale_zip.write_bytes(b"old archive")

    with pytest.raises(GitHubAPIError):
        download_repo_zip(
            "pallets",
            "flask",
            tmp_path,
        )

    assert not stale_zip.exists()


def test_download_repo_zip_not_found(monkeypatch, tmp_path):
    def fake_repo_info(owner, repo):
        return {
            "full_name": f"{owner}/{repo}",
            "default_branch": "main",
            "size_kb": 100,
            "language": "Python",
        }

    class FakeStreamResponse:
        status_code = 404

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "engine.fetch.get_repo_info",
        fake_repo_info,
    )
    monkeypatch.setattr(
        "engine.fetch.httpx.stream",
        lambda *args, **kwargs: FakeStreamResponse(),
    )

    stale_zip = tmp_path / "repo.zip"
    stale_zip.write_bytes(b"old archive")

    with pytest.raises(RepositoryNotFound):
        download_repo_zip(
            "pallets",
            "flask",
            tmp_path,
        )

    assert not stale_zip.exists()


def test_download_repo_zip_rejects_oversized_zip(monkeypatch, tmp_path):
    def fake_repo_info(owner, repo):
        return {
            "full_name": f"{owner}/{repo}",
            "default_branch": "main",
            "size_kb": 100,
            "language": "Python",
        }

    class FakeStreamResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_bytes(self):
            yield b"x" * (50 * 1024 * 1024 + 1)

    monkeypatch.setattr(
        "engine.fetch.get_repo_info",
        fake_repo_info,
    )
    monkeypatch.setattr(
        "engine.fetch.httpx.stream",
        lambda *args, **kwargs: FakeStreamResponse(),
    )

    with pytest.raises(RepositoryTooLarge):
        download_repo_zip(
            "pallets",
            "flask",
            tmp_path,
        )

    assert not (tmp_path / "repo.zip").exists()


def test_download_repo_zip_handles_network_error(monkeypatch, tmp_path):
    def fake_repo_info(owner, repo):
        return {
            "full_name": f"{owner}/{repo}",
            "default_branch": "main",
            "size_kb": 100,
            "language": "Python",
        }

    def fake_stream(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(
        "engine.fetch.get_repo_info",
        fake_repo_info,
    )
    monkeypatch.setattr(
        "engine.fetch.httpx.stream",
        fake_stream,
    )

    with pytest.raises(GitHubAPIError):
        download_repo_zip(
            "pallets",
            "flask",
            tmp_path,
        )