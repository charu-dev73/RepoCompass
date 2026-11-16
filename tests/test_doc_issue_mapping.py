
from pathlib import Path

import pytest

from engine.doc_issue_mapping import map_issue_to_docs


def create_doc(tmp_path, name, content):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_stream_issue_prefers_quickstart(tmp_path):
    quickstart = create_doc(
        tmp_path,
        "docs/user/quickstart.rst",
        """
        Streaming Requests
        ------------------

        You can stream large downloads with stream=True.
        Use iter_content() to process downloaded content in chunks.
        """,
    )

    advanced = create_doc(
        tmp_path,
        "docs/user/advanced.rst",
        """
        Advanced Usage
        --------------

        This section covers prepared requests and sessions.
        """,
    )

    history = create_doc(
        tmp_path,
        "HISTORY.md",
        """
        Historical changes and bug fixes.
        """,
    )

    issue = {
        "title": "How to stream large downloads",
        "body": "I want to use stream=True and iter_content().",
    }

    results = map_issue_to_docs(
        issue,
        [advanced, history, quickstart],
    )

    assert results
    assert results[0]["path"] == quickstart


def test_ssl_issue_prefers_relevant_troubleshooting_docs(tmp_path):
    advanced = create_doc(
        tmp_path,
        "docs/user/advanced.rst",
        """
        SSL Certificate Verification
        ----------------------------

        Requests verifies SSL certificates by default.
        You can configure certificate verification using verify.
        """,
    )

    faq = create_doc(
        tmp_path,
        "docs/community/faq.rst",
        """
        SSL Certificate Errors
        ---------------------

        Certificate verification failures can occur.
        Check your certificates and SSL configuration.
        """,
    )

    quickstart = create_doc(
        tmp_path,
        "docs/user/quickstart.rst",
        """
        Making Requests
        ----------------

        This guide explains basic GET and POST requests.
        """,
    )

    history = create_doc(
        tmp_path,
        "HISTORY.md",
        """
        Historical SSL certificate bug fixes.
        """,
    )

    issue = {
        "title": "SSL certificate verification failure",
        "body": (
            "I receive an SSL certificate verification error. "
            "How can I troubleshoot this problem?"
        ),
    }

    results = map_issue_to_docs(
        issue,
        [quickstart, history, faq, advanced],
    )

    result_paths = [result["path"] for result in results]

    assert advanced in result_paths
    assert faq in result_paths
    assert quickstart not in result_paths
    assert history in result_paths

    scores = {
        result["path"]: result["score"]
        for result in results
    }
    assert scores[history] < scores[advanced]


def test_unrelated_document_is_not_returned(tmp_path):
    doc = create_doc(
        tmp_path,
        "docs/user/install.rst",
        """
        Installation
        ------------

        Install the package using pip.
        """,
    )

    issue = {
        "title": "How does connection pooling work?",
        "body": "I want to understand connection pool management.",
    }

    results = map_issue_to_docs(issue, [doc])

    assert results == []


def test_zero_limit_returns_empty_list(tmp_path):
    doc = create_doc(
        tmp_path,
        "docs/user/quickstart.rst",
        "Streaming downloads with stream=True.",
    )

    issue = {
        "title": "Streaming downloads",
        "body": "How do I stream downloads?",
    }

    assert map_issue_to_docs(issue, [doc], limit=0) == []


def test_results_are_deterministic(tmp_path):
    first = create_doc(
        tmp_path,
        "docs/a.rst",
        "Streaming downloads using stream=True.",
    )

    second = create_doc(
        tmp_path,
        "docs/b.rst",
        "Streaming downloads using stream=True.",
    )

    issue = {
        "title": "Streaming downloads",
        "body": "How do I use stream=True?",
    }

    first_run = map_issue_to_docs(issue, [second, first])
    second_run = map_issue_to_docs(issue, [first, second])

    assert first_run == second_run


def test_sampleproject_210_does_not_match_readme(tmp_path):
    readme = create_doc(
        tmp_path,
        "README.md",
        """
        # A sample Python project

        A sample project that exists as an aid to the Python Packaging
        User Guide.

        This project does not aim to cover best practices for Python
        project development as a whole. For example, it does not provide
        guidance or tool recommendations for version control,
        documentation, or testing.

        Typical contents would include an overview of the project, basic
        usage examples, etc. A "What's New" section is appropriate.

        [src]: https://github.com/pypa/sampleproject
        """,
    )

    issue = {
        "title": "Flake8 configuration should not use select",
        "body": (
            "The flake8 configuration in tox.ini uses the `select` option:\n"
            "https://github.com/pypa/sampleproject/blob/main/tox.ini#L45\n\n"
            "The Black website has [section on interoperability]"
            "(https://black.readthedocs.io/en/stable/guides/"
            "using_black_with_other_tools.html)\n\n"
            "The [flake8 documentation](https://flake8.pycqa.org/en/latest/"
            "user/options.html#cmdoption-flake8-select) states:\n"
            "> You usually do not need to specify this option as the "
            "default includes all installed plugin codes."
        ),
    }

    assert map_issue_to_docs(issue, [readme]) == []


def test_url_fragments_do_not_create_body_matches(tmp_path):
    doc = create_doc(
        tmp_path,
        "docs/guide.rst",
        "GitHub example repository connection documentation.",
    )

    issue = {
        "title": "Unexpected behavior",
        "body": "See https://github.com/example/repo/connection",
    }

    assert map_issue_to_docs(issue, [doc]) == []


@pytest.mark.parametrize(
    "term",
    [
        "not",
        "no",
        "all",
        "any",
        "only",
        "other",
        "before",
        "after",
        "because",
        "section",
        "key",
    ],
)
def test_low_information_title_terms_do_not_match(tmp_path, term):
    doc = create_doc(
        tmp_path,
        "docs/notes.rst",
        f"Notes about {term}.",
    )

    issue = {
        "title": f"Widget {term} behavior",
        "body": "",
    }

    assert map_issue_to_docs(issue, [doc]) == []


def test_two_generic_body_terms_do_not_qualify(tmp_path):
    doc = create_doc(
        tmp_path,
        "docs/notes.rst",
        "This section explains a key setting.",
    )

    issue = {
        "title": "Unrelated behavior",
        "body": "section key",
    }

    assert map_issue_to_docs(issue, [doc]) == []


def test_single_body_term_does_not_qualify(tmp_path):
    doc = create_doc(
        tmp_path,
        "docs/guide.rst",
        "Connection pooling is documented.",
    )

    issue = {
        "title": "Unexpected behavior",
        "body": "connection",
    }

    assert map_issue_to_docs(issue, [doc]) == []


def test_two_meaningful_body_terms_still_qualify(tmp_path):
    doc = create_doc(
        tmp_path,
        "docs/guide.rst",
        "Connection pooling is documented.",
    )

    issue = {
        "title": "Unexpected behavior",
        "body": "connection pooling",
    }

    results = map_issue_to_docs(issue, [doc])

    assert [result["path"] for result in results] == [doc]


def test_negation_does_not_hide_relevant_title_terms(tmp_path):
    doc = create_doc(
        tmp_path,
        "docs/user/quickstart.rst",
        "Streaming downloads with stream=True.",
    )

    issue = {
        "title": "Streaming is not working",
        "body": "Downloads fail.",
    }

    results = map_issue_to_docs(issue, [doc])

    assert [result["path"] for result in results] == [doc]


def test_pyproject_issue_does_not_use_generic_not_or_key_reasons(
    tmp_path,
):
    readme = create_doc(
        tmp_path,
        "README.md",
        """
        # Sample project

        The metadata is defined in the pyproject.toml file. Edit the key
        set to adapt the sample project. This does not include packaging
        guidance.
        """,
    )

    issue = {
        "title": (
            'pyproject.toml: references a "python_requires" key '
            "that does not exist"
        ),
        "body": (
            "See https://github.com/pypa/sampleproject/blob/main/"
            "pyproject.toml#L89"
        ),
    }

    results = map_issue_to_docs(issue, [readme])

    assert results
    reasons = results[0]["reasons"]
    assert not any("'not'" in reason for reason in reasons)
    assert not any("'key'" in reason for reason in reasons)
    assert any("'pyproject'" in reason for reason in reasons)
