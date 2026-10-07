from pathlib import Path

from engine.parse import parse_source

P = Path("example.py")


def test_docstring_keeps_only_first_line():
    source = '"""Handles login.\n\nLonger explanation here.\n"""\n'
    assert parse_source(source, P).docstring == "Handles login."


def test_missing_docstring_is_none():
    assert parse_source("x = 1\n", P).docstring is None


def test_collects_top_level_functions_and_classes_only():
    source = (
        "def top():\n"
        "    def inner():\n"
        "        pass\n"
        "\n"
        "async def fetch():\n"
        "    pass\n"
        "\n"
        "class Thing:\n"
        "    def method(self):\n"
        "        pass\n"
    )
    info = parse_source(source, P)
    assert info.functions == ["top", "fetch"]
    assert info.classes == ["Thing"]


def test_empty_source():
    info = parse_source("", P)
    assert info.line_count == 0
    assert info.parse_error is None
    assert info.functions == []


def test_line_count():
    assert parse_source("a = 1\nb = 2\n", P).line_count == 2


def test_syntax_error_is_recorded_not_raised():
    info = parse_source("def broken(:\n    pass\n", P)
    assert info.parse_error is not None
    assert info.parse_error.startswith("SyntaxError")
    assert info.line_count == 2


def test_python2_code_is_a_parse_error():
    info = parse_source('print "hello"\n', P)
    assert info.parse_error is not None


def test_null_bytes_do_not_crash():
    info = parse_source(b"x = 1\x00\n", P)
    assert info.parse_error is not None


def test_source_is_parsed_but_never_executed():
    info = parse_source('raise RuntimeError("this must never run")\n', P)
    assert info.parse_error is None