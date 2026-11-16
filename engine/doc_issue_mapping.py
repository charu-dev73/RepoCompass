
"""Match documentation issues to relevant repository documentation."""

import re
from pathlib import Path
from typing import Any


STOPWORDS = {
    "a", "after", "all", "an", "and", "any", "are", "as", "at",
    "be", "been", "before", "because", "but", "by", "can",
    "could", "do", "does", "for", "from", "get", "has", "have",
    "how", "i", "if", "in", "into", "is", "it", "its", "may",
    "might", "no", "not", "of", "on", "only", "or", "other",
    "our", "please", "should", "so", "some", "that", "the",
    "their", "them", "there", "these", "this", "to", "use",
    "using", "was", "we", "what", "when", "where", "which",
    "while", "with", "would", "you", "your",
}

GENERIC_TERMS = {
    "add", "change", "code", "document", "documentation",
    "error", "example", "file", "fix", "function", "issue",
    "key", "make", "method", "new", "option", "parameter",
    "problem", "request", "section", "support", "update",
    "value", "suggestion", "common", "guidance",
}

URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)

CHANGELOG_NAMES = {
    "changelog.md",
    "history.md",
    "changes.md",
    "news.md",
}

TROUBLESHOOTING_TERMS = {
    "troubleshoot", "troubleshooting", "verify", "verification",
    "certificate", "certificates", "ssl", "tls", "exception",
    "exceptions", "failure", "failures",
}


def _tokens(text: str) -> list[str]:
    """Extract useful lowercase terms from text."""
    text = URL_PATTERN.sub(" ", text)
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_+-]*", text.lower())

    return [
        word
        for word in words
        if len(word) > 1 and word not in STOPWORDS
    ]


def _resolve_document_path(
    path: Path,
    root: Path | None,
) -> Path:
    """Resolve a relative documentation path against the repository root."""
    path = Path(path)

    if path.is_absolute() or root is None:
        return path

    return Path(root) / path


def _read_document(path: Path) -> str:
    """Read a documentation file safely."""
    try:
        return path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
    except OSError:
        return ""


def _paragraphs(text: str) -> list[str]:
    """Split a document into paragraphs."""
    return [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip()
    ]


def _title_phrases(title: str) -> set[str]:
    """Extract adjacent two-word and three-word title phrases."""
    words = [
        word
        for word in _tokens(title)
        if word not in GENERIC_TERMS
    ]

    phrases = set()

    for size in (2, 3):
        for index in range(len(words) - size + 1):
            phrases.add(" ".join(words[index:index + size]))

    return phrases


def _is_troubleshooting_issue(issue_text: str) -> bool:
    """Check whether the issue is mainly about troubleshooting."""
    return bool(
        set(_tokens(issue_text)) & TROUBLESHOOTING_TERMS
    )


def map_issue_to_docs(
    issue: dict[str, Any],
    doc_files: list[Path],
    root: Path | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Rank documentation files by their relevance to an issue."""

    if limit <= 0 or not doc_files:
        return []

    title = str(issue.get("title", ""))
    body = str(issue.get("body", ""))

    title_terms = set(_tokens(title)) - GENERIC_TERMS
    body_terms = set(_tokens(body)) - GENERIC_TERMS

    if not title_terms and not body_terms:
        return []

    title_phrases = _title_phrases(title)
    troubleshooting = _is_troubleshooting_issue(
        f"{title} {body}"
    )

    results = []

    for original_path in doc_files:
        original_path = Path(original_path)
        actual_path = _resolve_document_path(original_path, root)

        content = _read_document(actual_path)

        if not content:
            continue

        paragraphs = _paragraphs(content)
        score = 0
        reasons = []

        document_terms = set(_tokens(content))

        # Title terms are the strongest initial evidence.
        matching_title_terms = title_terms & document_terms

        for term in sorted(matching_title_terms):
            score += 10
            reasons.append(
                f"Issue title term '{term}' appears in the document."
            )

        # Body terms are weaker supporting evidence.
        matching_body_terms = (
            body_terms - title_terms
        ) & document_terms

        for term in sorted(matching_body_terms):
            score += 1

        if matching_body_terms:
            reasons.append(
                "Issue description contains terms also found in the document."
            )

        if not matching_title_terms and len(matching_body_terms) < 2:
            continue

        # Check whether relevant terms appear together in a paragraph.
        best_paragraph_matches = 0

        for paragraph in paragraphs:
            paragraph_lower = paragraph.lower()
            paragraph_terms = set(_tokens(paragraph))

            paragraph_title_matches = (
                title_terms & paragraph_terms
            )

            best_paragraph_matches = max(
                best_paragraph_matches,
                len(paragraph_title_matches),
            )

            for phrase in title_phrases:
                if phrase in paragraph_lower:
                    score += 12
                    reasons.append(
                        f"Related title phrase '{phrase}' appears in a paragraph."
                    )

        if best_paragraph_matches >= 2:
            score += best_paragraph_matches * 3

        # A documentation directory is only a small bonus.
        if score > 0:
            path_lower = str(original_path).lower()

            if "docs" in path_lower or "documentation" in path_lower:
                score += 3

        # Changelogs are weaker sources for troubleshooting guidance.
        if (
            troubleshooting
            and original_path.name.lower() in CHANGELOG_NAMES
        ):
            score -= 8

        if score > 0:
            results.append({
                "path": original_path,
                "score": score,
                "reasons": list(dict.fromkeys(reasons)),
            })

    results.sort(
        key=lambda result: (
            -result["score"],
            str(result["path"]).lower(),
        )
    )

    return results[:limit]
