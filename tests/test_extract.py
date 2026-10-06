import zipfile

import pytest

from engine.fetch import UnsafeArchiveError, extract_repo_zip


def test_extract_repo_zip_success(tmp_path):
    zip_path = tmp_path / "repo.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "pallets-flask-abc123/README.md",
            "# Flask",
        )
        archive.writestr(
            "pallets-flask-abc123/app.py",
            "print('hello')",
        )

    result = extract_repo_zip(zip_path, extract_dir)

    assert result == extract_dir / "pallets-flask-abc123"
    assert (result / "README.md").read_text() == "# Flask"
    assert (result / "app.py").read_text() == "print('hello')"


def test_extract_repo_zip_rejects_parent_traversal(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "pallets-flask-abc123/../../evil.txt",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, extract_dir)


def test_extract_repo_zip_rejects_absolute_path(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "/tmp/evil.txt",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, extract_dir)


def test_extract_repo_zip_rejects_multiple_top_level_directories(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "repo-one/file.txt",
            "one",
        )
        archive.writestr(
            "repo-two/file.txt",
            "two",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, extract_dir)


def test_extract_repo_zip_rejects_missing_top_level_directory(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "file.txt",
            "unexpected",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, extract_dir)