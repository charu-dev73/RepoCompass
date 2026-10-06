import httpx
import pytest

from engine.fetch import (
    GitHubAPIError,
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