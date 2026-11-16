import stat
import struct
import tempfile
import zipfile
from pathlib import Path

import httpx
import pytest

from engine.fetch import (
    GitHubAPIError,
    InvalidArchiveError,
    InvalidGitHubURL,
    RepositoryNotFound,
    UnsafeArchiveError,
    extract_repo_zip,
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


@pytest.mark.parametrize("status_code", [403, 429])
def test_get_repo_info_rate_limit(monkeypatch, status_code):
    def fake_get(*args, **kwargs):
        return httpx.Response(status_code)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GitHubAPIError):
        get_repo_info("pallets", "flask")


def test_get_repo_info_unexpected_status(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(500)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GitHubAPIError):
        get_repo_info("pallets", "flask")


def test_get_repo_info_rejects_invalid_json(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(200, content=b"not json")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GitHubAPIError):
        get_repo_info("pallets", "flask")


def test_get_repo_info_rejects_non_object_json(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GitHubAPIError):
        get_repo_info("pallets", "flask")


@pytest.mark.parametrize(
    "missing_field",
    ["full_name", "default_branch", "size"],
)
def test_get_repo_info_rejects_missing_required_fields(
    monkeypatch,
    missing_field,
):
    payload = {
        "full_name": "pallets/flask",
        "default_branch": "main",
        "size": 12311,
        "language": "Python",
    }
    payload.pop(missing_field)

    def fake_get(*args, **kwargs):
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GitHubAPIError):
        get_repo_info("pallets", "flask")


@pytest.mark.parametrize(
    "field, value",
    [
        ("full_name", None),
        ("full_name", 123),
        ("default_branch", None),
        ("default_branch", 123),
        ("size", "12311"),
        ("size", 12311.5),
        ("size", True),
        ("size", -1),
        ("language", 123),
        ("language", ["Python"]),
    ],
)
def test_get_repo_info_rejects_invalid_field_types(
    monkeypatch,
    field,
    value,
):
    payload = {
        "full_name": "pallets/flask",
        "default_branch": "main",
        "size": 12311,
        "language": "Python",
    }
    payload[field] = value

    def fake_get(*args, **kwargs):
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GitHubAPIError):
        get_repo_info("pallets", "flask")


def test_get_repo_info_accepts_null_language(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "full_name": "pallets/flask",
                "default_branch": "main",
                "size": 12311,
                "language": None,
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    assert get_repo_info("pallets", "flask")["language"] is None


def test_extract_repo_zip_extracts_regular_files(tmp_path):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/src/main.py",
            "print('hello')",
        )

    result = extract_repo_zip(zip_path, destination)

    assert result == destination / "project"
    assert (result / "src/main.py").read_text() == "print('hello')"


def test_extract_repo_zip_supports_temporary_directory():
    with tempfile.TemporaryDirectory(
        prefix="repocompass-test-"
    ) as temp_dir:
        zip_path = Path(temp_dir) / "repo.zip"
        destination = Path(temp_dir) / "extracted"

        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr(
                "project/main.py",
                "print('hello')",
            )

        result = extract_repo_zip(zip_path, destination)

        assert result == destination / "project"
        assert (result / "main.py").read_text() == "print('hello')"


def test_extract_repo_zip_extracts_to_relative_destination(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    zip_path = tmp_path / "repo.zip"
    destination = "relative/extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/main.py",
            "print('hello')",
        )

    result = extract_repo_zip(zip_path, destination)

    assert result == Path(destination) / "project"
    assert (result / "main.py").read_text() == "print('hello')"


def test_extract_repo_zip_skips_symbolic_links(tmp_path):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    symlink_info = zipfile.ZipInfo(
        "project/src/external"
    )
    symlink_info.create_system = 3
    symlink_info.external_attr = (
        (stat.S_IFLNK | 0o777) << 16
    )

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/src/main.py",
            "print('hello')",
        )
        archive.writestr(
            symlink_info,
            "../../outside",
        )

    result = extract_repo_zip(zip_path, destination)

    assert (result / "src/main.py").is_file()
    assert not (result / "src/external").exists()


def test_extract_repo_zip_rejects_pre_existing_symlink_root(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"
    outside = tmp_path / "outside"

    outside.mkdir()
    secret = outside / "secret.py"
    secret.write_text("original")

    destination.mkdir()
    (destination / "project").symlink_to(
        outside,
        target_is_directory=True,
    )

    symlink_info = zipfile.ZipInfo("project/external")
    symlink_info.create_system = 3
    symlink_info.external_attr = (
        (stat.S_IFLNK | 0o777) << 16
    )

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            symlink_info,
            "../../outside",
        )

    with pytest.raises(
        UnsafeArchiveError,
        match="real directory",
    ):
        extract_repo_zip(zip_path, destination)

    assert (destination / "project").is_symlink()
    assert secret.read_text() == "original"
    assert not (outside / "external").exists()
    assert [path.name for path in outside.iterdir()] == ["secret.py"]


def test_extract_repo_zip_rejects_path_traversal(tmp_path):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/../../outside.txt",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)


def test_extract_repo_zip_rejects_absolute_paths(tmp_path):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "/outside/file.py",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)


def test_extract_repo_zip_rejects_windows_paths(tmp_path):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            r"project\..\outside.py",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)


def test_extract_repo_zip_rejects_multiple_top_level_directories(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/main.py",
            "print('hello')",
        )
        archive.writestr(
            "another/file.py",
            "print('world')",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)


def test_extract_repo_zip_rejects_empty_archive(tmp_path):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w"):
        pass

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)


def test_extract_repo_zip_rejects_corrupt_archive(tmp_path):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    zip_path.write_bytes(b"not a zip archive")

    with pytest.raises(InvalidArchiveError):
        extract_repo_zip(zip_path, destination)


def make_truncated_compressed_zip(path):
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "project/main.py",
            "A" * 10_000,
        )

    data = path.read_bytes()

    with zipfile.ZipFile(path) as archive:
        member = archive.infolist()[0]

    local_offset = member.header_offset
    local_header_fields = struct.unpack(
        "<4s5H3L2H",
        data[local_offset:local_offset + 30],
    )
    name_length = local_header_fields[-2]
    extra_length = local_header_fields[-1]
    data_start = local_offset + 30 + name_length + extra_length

    local_header = data[local_offset:data_start]
    compressed_data = data[data_start:data_start + member.compress_size]

    eocd_offset = data.rfind(b"PK\x05\x06")
    central_size, central_offset = struct.unpack(
        "<LL",
        data[eocd_offset + 12:eocd_offset + 20],
    )
    central_directory = bytearray(
        data[central_offset:central_offset + central_size]
    )

    end_of_central_directory = struct.pack(
        "<4s4H2LH",
        b"PK\x05\x06",
        0,
        0,
        1,
        1,
        len(central_directory),
        0,
        0,
    )
    new_local_offset = len(central_directory) + len(
        end_of_central_directory
    )
    struct.pack_into("<L", central_directory, 42, new_local_offset)

    path.write_bytes(
        bytes(central_directory)
        + end_of_central_directory
        + local_header
        + compressed_data[:-2]
    )


@pytest.mark.parametrize(
    ("compression", "corrupt_offset"),
    [
        pytest.param(zipfile.ZIP_DEFLATED, 0, id="deflated"),
        pytest.param(zipfile.ZIP_BZIP2, 0, id="bzip2"),
        pytest.param(zipfile.ZIP_LZMA, 4, id="lzma"),
    ],
)
def test_extract_repo_zip_rejects_corrupt_compressed_data(
    tmp_path,
    compression,
    corrupt_offset,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "newparent" / "extracted"

    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=compression,
    ) as archive:
        archive.writestr(
            "project/main.py",
            "A" * 10_000,
        )

    with zipfile.ZipFile(zip_path) as archive:
        member = archive.infolist()[0]

    data = bytearray(zip_path.read_bytes())
    compressed_data_start = (
        member.header_offset
        + 30
        + len(member.filename.encode())
        + len(member.extra)
    )
    data[compressed_data_start + corrupt_offset] ^= 0xFF
    zip_path.write_bytes(data)

    with pytest.raises(InvalidArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not (tmp_path / "newparent").exists()


def test_extract_repo_zip_rejects_truncated_compressed_member(tmp_path):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "newparent" / "extracted"

    make_truncated_compressed_zip(zip_path)

    with pytest.raises(InvalidArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not (tmp_path / "newparent").exists()


def test_extract_repo_zip_cleans_created_destination_on_creation_failure(
    tmp_path,
    monkeypatch,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "newparent" / "extracted"
    original_mkdir = Path.mkdir

    def fail_destination_mkdir(self, *args, **kwargs):
        if self.name == "extracted":
            raise OSError("simulated failure")
        return original_mkdir(self, *args, **kwargs)

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/main.py",
            "print('hello')",
        )

    monkeypatch.setattr(Path, "mkdir", fail_destination_mkdir)

    with pytest.raises(
        UnsafeArchiveError,
        match="Could not create extraction destination",
    ):
        extract_repo_zip(zip_path, destination)

    assert not (tmp_path / "newparent").exists()


def test_extract_repo_zip_rejects_existing_symlink_directory(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"
    outside = tmp_path / "outside"

    outside.mkdir()
    destination.mkdir()

    (destination / "project").symlink_to(
        outside,
        target_is_directory=True,
    )

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/main.py",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not (outside / "main.py").exists()


def test_extract_repo_zip_rejects_duplicate_normalized_paths(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/a.txt",
            "first",
        )
        archive.writestr(
            "project//a.txt",
            "second",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not destination.exists()


def test_extract_repo_zip_rejects_file_followed_by_child(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/a",
            "file",
        )
        archive.writestr(
            "project/a/b.txt",
            "child",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not destination.exists()


def test_extract_repo_zip_rejects_child_followed_by_file(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/a/b.txt",
            "child",
        )
        archive.writestr(
            "project/a",
            "file",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not destination.exists()


def test_extract_repo_zip_rejects_existing_regular_file_target(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"
    project_dir = destination / "project"
    existing = project_dir / "existing.txt"

    project_dir.mkdir(parents=True)
    existing.write_text("original")

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/existing.txt",
            "replacement",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert existing.read_text() == "original"


def test_extract_repo_zip_cleans_partial_extraction_after_failure(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"
    project_dir = destination / "project"
    blocked_path = project_dir / "blocked.txt"
    unrelated = destination / "unrelated.txt"
    unrelated_link = destination / "unrelated-link.txt"

    project_dir.mkdir(parents=True)
    blocked_path.mkdir()
    unrelated.write_text("keep me")
    unrelated_link.symlink_to(unrelated)

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/ok.txt",
            "written first",
        )
        archive.writestr(
            "project/blocked.txt",
            "cannot be written over a directory",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not (project_dir / "ok.txt").exists()
    assert blocked_path.is_dir()
    assert unrelated.read_text() == "keep me"
    assert unrelated_link.is_symlink()
    assert unrelated_link.read_text() == "keep me"


def test_extract_repo_zip_rejects_existing_symlink_file_target(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"
    project_dir = destination / "project"
    outside = tmp_path / "outside.txt"

    project_dir.mkdir(parents=True)
    outside.write_text("safe")
    (project_dir / "link.txt").symlink_to(outside)

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/link.txt",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert outside.read_text() == "safe"
    assert (project_dir / "link.txt").is_symlink()


def test_extract_repo_zip_rejects_destination_symlink(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    target = tmp_path / "target"
    destination = tmp_path / "extracted"

    target.mkdir()
    destination.symlink_to(target, target_is_directory=True)

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/main.py",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert destination.is_symlink()
    assert not (target / "project").exists()


def test_extract_repo_zip_rejects_dangling_destination_symlink(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    target = tmp_path / "missing"
    destination = tmp_path / "extracted"

    destination.symlink_to(target, target_is_directory=True)

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/main.py",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert destination.is_symlink()
    assert not target.exists()


@pytest.mark.parametrize("target_exists", [True, False])
def test_extract_repo_zip_rejects_symlink_destination_ancestor(
    tmp_path,
    target_exists,
):
    zip_path = tmp_path / "repo.zip"
    target = tmp_path / "target"
    ancestor = tmp_path / "ancestor"
    destination = ancestor / "extracted"

    if target_exists:
        target.mkdir()

    ancestor.symlink_to(target, target_is_directory=True)

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/main.py",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert ancestor.is_symlink()
    assert not (target / "extracted").exists()

    if target_exists:
        assert target.is_dir()
    else:
        assert not target.exists()


def test_extract_repo_zip_rejects_deep_symlink_destination_ancestor(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    target = tmp_path / "target"
    ancestor = tmp_path / "ancestor"
    destination = ancestor / "nested" / "extracted"

    target.mkdir()
    ancestor.symlink_to(target, target_is_directory=True)

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/main.py",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert ancestor.is_symlink()
    assert not (target / "nested").exists()


def test_extract_repo_zip_rejection_preserves_symlink_target(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    target = tmp_path / "target"
    destination = tmp_path / "extracted"
    project_dir = target / "project"
    existing = project_dir / "existing.txt"

    project_dir.mkdir(parents=True)
    existing.write_text("original")
    destination.symlink_to(target, target_is_directory=True)

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/main.py",
            "malicious",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert destination.is_symlink()
    assert existing.read_text() == "original"
    assert not (project_dir / "main.py").exists()


def test_extract_repo_zip_rejects_directory_entry_without_trailing_slash(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    directory_info = zipfile.ZipInfo("project")
    directory_info.create_system = 3
    directory_info.external_attr = (
        (stat.S_IFDIR | 0o755) << 16
    )

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(directory_info, "")

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not destination.exists()


def test_extract_repo_zip_rejects_regular_file_with_trailing_slash(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    file_info = zipfile.ZipInfo("project/main.py/")
    file_info.create_system = 3
    file_info.external_attr = (
        (stat.S_IFREG | 0o644) << 16
    )

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(file_info, "malicious")

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not destination.exists()


def test_extract_repo_zip_rejects_empty_member_filename(
    tmp_path,
):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("", "malicious")

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not destination.exists()


def test_extract_repo_zip_rejects_special_archive_entries(tmp_path):
    zip_path = tmp_path / "repo.zip"
    destination = tmp_path / "extracted"

    fifo_info = zipfile.ZipInfo("project/fifo")
    fifo_info.create_system = 3
    fifo_info.external_attr = (
        (stat.S_IFIFO | 0o644) << 16
    )

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "project/main.py",
            "print('hello')",
        )
        archive.writestr(
            fifo_info,
            "",
        )

    with pytest.raises(UnsafeArchiveError):
        extract_repo_zip(zip_path, destination)

    assert not destination.exists()
