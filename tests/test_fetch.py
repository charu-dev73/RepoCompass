import httpx
import pytest

from engine.fetch import (
    GitHubAPIError,
    InvalidGitHubURL,
    RepositoryNotFound,
    get_repo_info,
    parse_github_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/pallets/flask",
        "https://github.com/pallets/flask/",
        "https://github.com/pallets/flask.git",
        "https://github.com/pallets/flask/tree/main/src",
        "http://github.com/pallets/flask",
        "https://www.github.com/pallets/flask",
        "  https://github.com/pallets/flask  ",
    ],
)
def test_valid_urls_return_owner_and_repo(url):
    assert parse_github_url(url) == ("pallets", "flask")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "pallets/flask",
        "https://gitlab.com/pallets/flask",
        "https://github.com/pallets",
        "https://github.com/",
        "ftp://github.com/pallets/flask",
        "https://github.com/pal lets/flask",
        "https://github.com/../flask",
        "https://github.com/pallets/..",
        "https://github.com/pallets/.git",
    ],
)
def test_invalid_urls_raise(url):
    with pytest.raises(InvalidGitHubURL):
        parse_github_url(url)


def test_get_repo_info_success(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "full_name": "pallets/flask",
                "default_branch": "main",
                "size": 12311,
                "language": "Python",
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = get_repo_info("pallets", "flask")

    assert result == {
        "full_name": "pallets/flask",
        "default_branch": "main",
        "size_kb": 12311,
        "language": "Python",
    }


def test_get_repo_info_not_found(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(RepositoryNotFound):
        get_repo_info("pallets", "does-not-exist")


def test_get_repo_info_rate_limit(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(403)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GitHubAPIError):
        get_repo_info("pallets", "flask")


def test_get_repo_info_unexpected_status(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(500)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GitHubAPIError):
        get_repo_info("pallets", "flask")