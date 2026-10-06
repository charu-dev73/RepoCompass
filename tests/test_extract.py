import zipfile

import pytest

from engine.fetch import (
    InvalidArchiveError,
    UnsafeArchiveError,
    extract_repo_zip,
)


def test_extract_repo_zip_success(tmp_path):
    zip_path = tmp_path / "repo.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "pallets-flask-1234/README.md",
            "hello",
        )
        archive.writestr(
            "pallets-flask-1234/app.py",
            "print('hello')",
        )

    result = extract_repo_zip(zip_path, extract_dir)

    assert result == extract_dir / "pallets-flask-1234"
    assert (result / "README.md").read_text() == "hello"
    assert (result / "app.py").read_text() == "print('hello')"


def test_extract_repo_zip_rejects_parent_traversal(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "../../evil.txt",
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


def test_extract_repo_zip_rejects_too_many_files(tmp_path, monkeypatch):
    zip_path = tmp_path / "too_many.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        for index in range(11):
            archive.writestr(
                f"repo/file-{index}.txt",
                "data",
            )

    monkeypatch.setattr(
        "engine.fetch.MAX_EXTRACT_FILES",
        10,
    )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, extract_dir)


def test_extract_repo_zip_rejects_zip_bomb_size(tmp_path, monkeypatch):
    zip_path = tmp_path / "bomb.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "repo/large.txt",
            "A" * 100,
        )

    monkeypatch.setattr(
        "engine.fetch.MAX_EXTRACT_BYTES",
        50,
    )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, extract_dir)


def test_extract_repo_zip_rejects_symlink(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        info = zipfile.ZipInfo(
            "repo/passwd",
        )

        # Mark the ZIP entry as a Unix symbolic link.
        info.create_system = 3
        info.external_attr = 0o120777 << 16

        archive.writestr(
            info,
            "../../etc/passwd",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, extract_dir)


def test_extract_repo_zip_rejects_corrupt_zip(tmp_path):
    zip_path = tmp_path / "corrupt.zip"
    extract_dir = tmp_path / "extracted"

    zip_path.write_bytes(
        b"this is not a valid zip archive"
    )

    with pytest.raises(InvalidArchiveError):
        extract_repo_zip(zip_path, extract_dir)