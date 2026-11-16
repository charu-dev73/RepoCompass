from pathlib import Path

from engine.issue_mapping import map_issue_to_files
from engine.parse import parse_source


def make_file(path, source):
    return parse_source(source, Path(path))


def test_exact_file_path_mention_gets_strong_match():
    files = [
        make_file("src/auth.py", "def authenticate():\n    pass\n"),
        make_file("src/database.py", "def connect():\n    pass\n"),
    ]

    issue = {
        "title": "Fix authentication",
        "body": "The problem occurs in `src/auth.py`.",
    }

    results = map_issue_to_files(issue, files)

    assert results
    assert results[0]["path"] == "src/auth.py"
    assert results[0]["score"] >= 100
    assert "Issue explicitly mentions this file" in results[0]["reasons"]


def test_backticked_function_identifier_matches():
    files = [
        make_file("src/auth.py", "def refresh_token():\n    pass\n"),
        make_file("src/database.py", "def connect():\n    pass\n"),
    ]

    issue = {
        "title": "Fix token refresh",
        "body": "The `refresh_token` function fails.",
    }

    results = map_issue_to_files(issue, files)

    assert results
    assert results[0]["path"] == "src/auth.py"
    assert results[0]["score"] >= 60


def test_filename_match_is_detected():
    files = [
        make_file("src/authentication.py", "def login():\n    pass\n"),
        make_file("src/database.py", "def connect():\n    pass\n"),
    ]

    issue = {"title": "Authentication problem", "body": ""}

    results = map_issue_to_files(issue, files)

    assert results
    assert results[0]["path"] == "src/authentication.py"


def test_returns_no_results_without_matching_evidence():
    files = [
        make_file("src/database.py", "def connect():\n    pass\n"),
    ]

    issue = {"title": "Fix the issue", "body": None}

    assert map_issue_to_files(issue, files) == []


def test_returns_no_results_for_empty_files():
    issue = {
        "title": "Fix authentication",
        "body": "Token refresh is broken.",
    }

    assert map_issue_to_files(issue, []) == []


def test_non_positive_limit_returns_empty():
    files = [
        make_file("src/auth.py", "def authenticate():\n    pass\n"),
    ]

    issue = {"title": "Fix authentication"}

    assert map_issue_to_files(issue, files, limit=0) == []


def test_results_are_deterministic():
    first = make_file("src/auth.py", "def authenticate():\n    pass\n")
    second = make_file("lib/auth.py", "def authenticate():\n    pass\n")

    issue = {"title": "Authentication problem", "body": ""}

    result_one = map_issue_to_files(issue, [first, second])
    result_two = map_issue_to_files(issue, [second, first])

    assert result_one == result_two


def test_respects_result_limit():
    files = [
        make_file(
            f"src/authentication_{number}.py",
            "def authenticate():\n    pass\n",
        )
        for number in range(5)
    ]

    issue = {"title": "Authentication problem", "body": ""}

    results = map_issue_to_files(issue, files, limit=2)

    assert len(results) == 2


def test_test_files_receive_lower_score():
    implementation = make_file(
        "src/auth.py",
        "def authenticate():\n    pass\n",
    )

    test_file = make_file(
        "tests/test_auth.py",
        "def test_authenticate():\n    pass\n",
    )

    issue = {"title": "Auth problem", "body": ""}

    results = map_issue_to_files(issue, [implementation, test_file])

    scores = {result["path"]: result["score"] for result in results}

    assert scores["src/auth.py"] > scores["tests/test_auth.py"]


def test_class_identifier_matches():
    files = [
        make_file("src/auth.py", "class TokenManager:\n    pass\n"),
        make_file("src/database.py", "class DatabaseConnection:\n    pass\n"),
    ]

    issue = {
        "title": "Token manager is failing",
        "body": "The `TokenManager` class raises an exception.",
    }

    results = map_issue_to_files(issue, files)

    assert results
    assert results[0]["path"] == "src/auth.py"
    assert any("TokenManager" in reason for reason in results[0]["reasons"])


def test_identifier_matching_handles_snake_case():
    files = [
        make_file("src/auth.py", "class TokenManager:\n    pass\n"),
    ]

    issue = {
        "title": "Token manager failure",
        "body": "The `token_manager` class is failing.",
    }

    results = map_issue_to_files(issue, files)

    assert results
    assert results[0]["path"] == "src/auth.py"


def test_issue_body_matches_module_docstring():
    files = [
        make_file(
            "src/security.py",
            '"""Handles token refresh and credential validation."""\n'
            "def validate():\n    pass\n",
        ),
        make_file(
            "src/database.py",
            '"""Manages database connections."""\n'
            "def connect():\n    pass\n",
        ),
    ]

    issue = {
        "title": "Authentication fails",
        "body": "Token refresh breaks when credentials expire.",
    }

    results = map_issue_to_files(issue, files)

    assert results
    assert results[0]["path"] == "src/security.py"
    assert any("Docstring" in reason for reason in results[0]["reasons"])


def test_stronger_filename_match_ranks_above_weak_docstring_match():
    files = [
        make_file(
            "src/security.py",
            '"""Handles token refresh and credential validation."""\n',
        ),
        make_file(
            "src/token_refresh.py",
            '"""Handles background processing."""\n',
        ),
    ]

    issue = {
        "title": "Token refresh fails",
        "body": "",
    }

    results = map_issue_to_files(issue, files)

    assert results
    assert results[0]["path"] == "src/token_refresh.py"


def test_unrelated_file_does_not_get_recommended():
    files = [
        make_file(
            "src/security.py",
            '"""Handles token refresh and credential validation."""\n',
        ),
        make_file(
            "src/database.py",
            '"""Manages database connections."""\n',
        ),
    ]

    issue = {
        "title": "Improve image rendering",
        "body": "The canvas rendering is slow.",
    }

    results = map_issue_to_files(issue, files)

    assert results == []


def test_multiple_relevant_files_are_ranked_deterministically():
    files = [
        make_file(
            "src/security.py",
            '"""Handles token refresh and credential validation."""\n',
        ),
        make_file(
            "src/token_refresh.py",
            "def refresh_token():\n    pass\n",
        ),
        make_file(
            "src/database.py",
            '"""Manages database connections."""\n',
        ),
    ]

    issue = {
        "title": "Token refresh fails",
        "body": "The refresh_token operation breaks.",
    }

    first = map_issue_to_files(issue, files)
    second = map_issue_to_files(issue, list(reversed(files)))

    assert first == second
    assert first[0]["path"] == "src/token_refresh.py"


def test_singular_issue_word_matches_plural_filename():
    files = [
        make_file(
            "src/credential.py",
            "def validate_credential():\n    pass\n",
        ),
        make_file(
            "src/database.py",
            "def connect():\n    pass\n",
        ),
    ]

    issue = {
        "title": "Credentials validation fails",
        "body": "",
    }

    results = map_issue_to_files(issue, files)

    assert results
    assert results[0]["path"] == "src/credential.py"


def test_plural_issue_word_matches_singular_docstring():
    files = [
        make_file(
            "src/security.py",
            '"""Handles credential validation."""\n',
        ),
        make_file(
            "src/database.py",
            '"""Manages database connections."""\n',
        ),
    ]

    issue = {
        "title": "Authentication problem",
        "body": "Credentials are rejected unexpectedly.",
    }

    results = map_issue_to_files(issue, files)

    assert results
    assert results[0]["path"] == "src/security.py"


def test_plural_normalization_does_not_change_exact_identifiers():
    files = [
        make_file(
            "src/auth.py",
            "def refresh_tokens():\n    pass\n",
        ),
    ]

    issue = {
        "title": "Token refresh fails",
        "body": "The `refresh_tokens` function is broken.",
    }

    results = map_issue_to_files(issue, files)

    assert results
    assert results[0]["path"] == "src/auth.py"
    assert any(
        "Defines the mentioned identifier `refresh_tokens`" in reason
        for reason in results[0]["reasons"]
    )


def test_generic_request_words_do_not_create_recommendations():
    files = [
        make_file(
            "src/utils.py",
            "def get_response_body():\n"
            "    pass\n"
            "def set_default_content():\n"
            "    pass\n",
        ),
        make_file(
            "src/cookies.py",
            "def create_request():\n"
            "    pass\n"
            "def remove_response():\n"
            "    pass\n",
        ),
        make_file(
            "src/sessions.py",
            "def get_user_session():\n"
            "    pass\n",
        ),
    ]

    issue = {
        "title": "Documentation for stream parameter is ambiguous",
        "body": (
            "The request body and response content are unclear. "
            "The default value should be explained to the user."
        ),
    }

    assert map_issue_to_files(issue, files) == []


def test_generic_ssl_documentation_words_do_not_create_recommendations():
    files = [
        make_file(
            "src/exceptions.py",
            '"""Handles request exceptions and errors."""\n'
            "class RequestException:\n"
            "    pass\n",
        ),
        make_file(
            "tests/test_help.py",
            "def test_request_help():\n"
            "    pass\n",
        ),
        make_file(
            "src/status_codes.py",
            '"""Contains common response status values."""\n',
        ),
        make_file(
            "src/adapters.py",
            "def get_response():\n"
            "    pass\n",
        ),
    ]

    issue = {
        "title": (
            "Documentation suggestion: Add troubleshooting guidance "
            "for common SSL verification errors"
        ),
        "body": (
            "Please add documentation explaining common errors and "
            "how users can troubleshoot verification problems."
        ),
    }

    assert map_issue_to_files(issue, files) == []


def test_directory_name_alone_does_not_create_recommendation():
    files = [
        make_file(
            "src/auth/security.py",
            "def perform_check():\n"
            "    pass\n",
        ),
        make_file(
            "src/database/connection.py",
            "def open_connection():\n"
            "    pass\n",
        ),
    ]

    issue = {
        "title": "Authentication problem",
        "body": "",
    }

    assert map_issue_to_files(issue, files) == []