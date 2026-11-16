
"""Map beginner-friendly issues to likely relevant Python files."""

import re
from collections import Counter
from pathlib import Path
from typing import Any

from engine.parse import FileInfo


MAX_BODY_LENGTH = 3000
MAX_RESULTS = 3

# Words that are too broad to identify a particular source file.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being",
    "but", "by", "can", "could", "do", "does", "for", "from",
    "get", "got", "has", "have", "how", "if", "in", "into",
    "is", "it", "its", "may", "might", "of", "on", "or", "our",
    "should", "so", "some", "such", "than", "that", "the",
    "their", "them", "then", "there", "these", "they", "this",
    "those", "to", "up", "us", "was", "we", "were", "what",
    "when", "where", "which", "who", "why", "will", "with",
    "would", "you", "your",

    "add", "change", "code", "error", "errors", "fail", "failed",
    "fix", "issue", "make", "problem", "problems", "support",
    "update", "use", "using", "work", "working",

    "stream", "ssl", "verification", "troubleshooting",
    "guidance", "common", "parameter", "ambiguous",

    # Common words in issue descriptions and across many codebases.
    "request", "requests", "response", "responses", "body",
    "content", "data", "default", "value", "values", "user",
    "users", "set", "get", "return", "returns", "result",
    "results", "function", "method", "class", "module",
    "file", "files", "line", "exception", "exceptions",
    "test", "tests", "testing", "documentation", "docs",
    "expected", "actual", "currently", "also",
    "one", "two", "new", "old", "different", "working",
}


def _normalize_word(word: str) -> str:
    """Apply small, deterministic plural normalization."""
    word = word.lower()

    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"

    if len(word) > 4 and word.endswith(
        ("sses", "shes", "ches", "xes", "zes")
    ):
        return word[:-2]

    if (
        len(word) > 3
        and word.endswith("s")
        and not word.endswith(("ss", "us", "is"))
    ):
        return word[:-1]

    return word


def _split_identifier(value: str) -> list[str]:
    """Split snake_case, camelCase, dotted names and ordinary text."""
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    parts = re.findall(r"[A-Za-z0-9]+", value)

    words = []

    for part in parts:
        normalized = _normalize_word(part)

        if len(normalized) > 1 and normalized not in STOPWORDS:
            words.append(normalized)

    return words


def _issue_signals(issue: dict[str, Any]) -> dict[str, Any]:
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")[:MAX_BODY_LENGTH]
    combined = f"{title} {body}"

    title_words = set(_split_identifier(title))
    body_words = set(_split_identifier(body))

    backticked = re.findall(r"`([^`]+)`", combined)

    identifiers = {
        item.strip()
        for item in backticked
        if item.strip()
    }

    paths = {
        item.strip()
        for item in re.findall(
            r"(?<![\w/.-])(?:[\w.-]+/)*[\w.-]+\.py",
            combined,
        )
    }

    return {
        "title_words": title_words,
        "body_words": body_words,
        "identifiers": identifiers,
        "paths": paths,
        "mentions_tests": bool(
            re.search(r"\b(test|tests|testing)\b", combined, re.I)
        ),
    }


def _name_of(value: Any) -> str:
    """Get a name from either a string or a parsed definition object."""
    if isinstance(value, str):
        return value

    name = getattr(value, "name", None)
    return name if isinstance(name, str) else ""


def _file_identifiers(info: FileInfo) -> set[str]:
    identifiers = set()

    for attribute in ("functions", "classes"):
        values = getattr(info, attribute, []) or []

        for value in values:
            name = _name_of(value)

            if name:
                identifiers.add(name)

    return identifiers


def _is_test_file(path: str) -> bool:
    parts = Path(path).parts
    filename = Path(path).name.lower()

    return (
        "tests" in {part.lower() for part in parts}
        or filename.startswith("test_")
        or filename.endswith("_test.py")
    )


def _has_distinctive_match(
    matches: set[str],
    document_frequency: Counter,
) -> bool:
    """A single match is useful only when it is reasonably distinctive."""
    return any(
        len(word) >= 9 and document_frequency[word] <= 2
        for word in matches
    )


def map_issue_to_files(
    issue: dict[str, Any],
    files: list[FileInfo],
    limit: int = MAX_RESULTS,
) -> list[dict[str, Any]]:
    """Return files with sufficient evidence of relevance to an issue."""
    if limit <= 0 or not files:
        return []

    signals = _issue_signals(issue)

    title_words = signals["title_words"]
    body_words = signals["body_words"]

    if (
        not title_words
        and not body_words
        and not signals["paths"]
        and not signals["identifiers"]
    ):
        return []

    file_data = []

    for info in files:
        path = str(info.path).replace("\\", "/")
        filename = Path(path).stem

        filename_words = set(_split_identifier(filename))
        identifiers = _file_identifiers(info)

        identifier_words = set()

        for identifier in identifiers:
            identifier_words.update(_split_identifier(identifier))

        docstring = str(getattr(info, "docstring", None) or "")
        docstring_words = set(_split_identifier(docstring))

        directory_words = set()

        for part in Path(path).parts[:-1]:
            directory_words.update(_split_identifier(part))

        file_data.append({
            "path": path,
            "filename_words": filename_words,
            "identifiers": identifiers,
            "identifier_words": identifier_words,
            "docstring_words": docstring_words,
            "directory_words": directory_words,
        })

    document_frequency = Counter()

    for item in file_data:
        document_words = (
            item["filename_words"]
            | item["identifier_words"]
            | item["docstring_words"]
            | item["directory_words"]
        )
        document_frequency.update(document_words)

    results = []

    for item in file_data:
        path = item["path"]
        score = 0
        reasons = []

        exact_path_match = path in signals["paths"]

        if exact_path_match:
            score += 100
            reasons.append("Issue explicitly mentions this file")

        exact_identifiers = (
            signals["identifiers"] & item["identifiers"]
        )

        for identifier in sorted(exact_identifiers):
            score += 60
            reasons.append(
                f"Defines the mentioned identifier `{identifier}`"
            )

        title_filename_matches = (
            title_words & item["filename_words"]
        )
        body_filename_matches = (
            body_words & item["filename_words"]
        )

        for word in sorted(title_filename_matches):
            score += 20
            reasons.append(
                f"Filename matches issue title: {word}"
            )

        for word in sorted(
            body_filename_matches - title_filename_matches
        ):
            score += 8
            reasons.append(
                f"Filename matches issue description: {word}"
            )

        title_identifier_matches = (
            title_words & item["identifier_words"]
        )
        body_identifier_matches = (
            body_words & item["identifier_words"]
        )

        for word in sorted(title_identifier_matches):
            score += 15
            reasons.append(
                f"Function or class name matches issue title: {word}"
            )

        for word in sorted(
            body_identifier_matches - title_identifier_matches
        ):
            score += 5
            reasons.append(
                f"Function or class name matches issue description: {word}"
            )

        title_doc_matches = (
            title_words & item["docstring_words"]
        )
        body_doc_matches = (
            body_words & item["docstring_words"]
        )
        doc_matches = title_doc_matches | body_doc_matches

        for word in sorted(title_doc_matches):
            score += 4
            reasons.append(
                f"Docstring matches issue title: {word}"
            )

        for word in sorted(
            body_doc_matches - title_doc_matches
        ):
            score += 2
            reasons.append(
                f"Docstring matches issue description: {word}"
            )

        # Directory names are context only. They never create a match.
        strong_filename_evidence = bool(
            title_filename_matches
            or len(body_filename_matches) >= 2
            or _has_distinctive_match(
                body_filename_matches,
                document_frequency,
            )
        )

        # Body identifier matches must be distinctive.
        # Two generic names like create/remove are not enough.
        strong_identifier_evidence = bool(
            title_identifier_matches
            or _has_distinctive_match(
                body_identifier_matches,
                document_frequency,
            )
        )

        docstring_evidence = bool(
            len(doc_matches) >= 2
            or _has_distinctive_match(
                doc_matches,
                document_frequency,
            )
        )

        has_evidence = bool(
            exact_path_match
            or exact_identifiers
            or strong_filename_evidence
            or strong_identifier_evidence
            or docstring_evidence
        )

        if not has_evidence:
            continue

        # Test files are less likely to contain the implementation.
        if _is_test_file(path) and not signals["mentions_tests"]:
            score = score // 2

        if score <= 0:
            continue

        results.append({
            "path": path,
            "score": score,
            "reasons": reasons,
        })

    results.sort(
        key=lambda result: (
            -result["score"],
            result["path"],
        )
    )

    return results[:limit]
