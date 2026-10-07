from pathlib import Path

from engine.parse import ImportRecord, parse_source

P = Path("example.py")


def imports_of(source):
    return parse_source(source, P).imports


def test_plain_import():
    assert imports_of("import os\n") == [ImportRecord(module="os", lineno=1)]


def test_multiple_modules_on_one_line_become_separate_records():
    records = imports_of("import os, sys\n")
    assert [r.module for r in records] == ["os", "sys"]
    assert [r.lineno for r in records] == [1, 1]


def test_dotted_import_with_alias_keeps_real_module_name():
    records = imports_of("import a.b.c as x\n")
    assert records == [ImportRecord(module="a.b.c", lineno=1)]


def test_from_import_collects_names():
    records = imports_of("from a.b import c, d\n")
    assert records == [ImportRecord(module="a.b", names=["c", "d"], level=0, lineno=1)]


def test_from_import_alias_keeps_original_name():
    records = imports_of("from a import b as c\n")
    assert records[0].names == ["b"]


def test_star_import():
    records = imports_of("from a import *\n")
    assert records[0].names == ["*"]


def test_relative_import_without_module():
    records = imports_of("from . import x\n")
    assert records == [ImportRecord(module=None, names=["x"], level=1, lineno=1)]


def test_relative_import_with_module_and_levels():
    records = imports_of("from ..pkg.mod import z\n")
    assert records == [ImportRecord(module="pkg.mod", names=["z"], level=2, lineno=1)]


def test_future_import_is_recorded():
    records = imports_of("from __future__ import annotations\n")
    assert records[0].module == "__future__"


def test_imports_inside_functions_and_try_blocks_are_found():
    source = (
        "try:\n"
        "    import ujson as json\n"
        "except ImportError:\n"
        "    import json\n"
        "\n"
        "def load():\n"
        "    from os import path\n"
    )
    records = imports_of(source)
    assert [r.module for r in records] == ["ujson", "json", "os"]
    assert [r.lineno for r in records] == [2, 4, 7]


def test_imports_are_sorted_by_line_number():
    source = "def f():\n    import json\nimport os\n"
    records = imports_of(source)
    assert [r.module for r in records] == ["json", "os"]
    assert [r.lineno for r in records] == [2, 3]


def test_import_text_inside_a_string_is_not_an_import():
    source = 'x = "import os"\n# import sys\n'
    assert imports_of(source) == []


def test_parse_error_gives_no_imports():
    info = parse_source("import os\ndef broken(:\n", P)
    assert info.parse_error is not None
    assert info.imports == []