import pytest

from engine.fetch import InvalidGitHubURL, parse_github_url


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