from pathlib import Path

import pytest

from engine.parse import parse_source

P = Path("example.py")


def has_guard(source):
    return parse_source(source, P).has_main_guard


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            'if __name__ == "__main__":\n    main()\n',
            id="double-quotes",
        ),
        pytest.param(
            "if __name__ == '__main__':\n    main()\n",
            id="single-quotes",
        ),
        pytest.param(
            'if "__main__" == __name__:\n    main()\n',
            id="reversed-order",
        ),
        pytest.param(
            'import sys\n\ndef main():\n    pass\n\nif __name__ == "__main__":\n    main()\n',
            id="after-other-code",
        ),
    ],
)
def test_detects_main_guard(source):
    assert has_guard(source) is True


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("", id="empty-file"),
        pytest.param("def main():\n    pass\n", id="no-guard"),
        pytest.param(
            'def run():\n    if __name__ == "__main__":\n        pass\n',
            id="inside-function",
        ),
        pytest.param(
            'if __name__ == "other":\n    pass\n',
            id="different-string",
        ),
        pytest.param(
            'if name == "__main__":\n    pass\n',
            id="different-variable",
        ),
        pytest.param(
            'if __name__ != "__main__":\n    pass\n',
            id="not-equal",
        ),
        pytest.param(
            '# if __name__ == "__main__":\nx = "if __name__ == \'__main__\'"\n',
            id="comment-and-string-only",
        ),
        pytest.param(
            'is_main = __name__ == "__main__"\n',
            id="not-an-if-statement",
        ),
    ],
)
def test_not_a_main_guard(source):
    assert has_guard(source) is False


def test_parse_error_has_no_main_guard():
    assert has_guard(
        'if __name__ == "__main__":\n    def broken(:\n'
    ) is False