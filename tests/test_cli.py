import cli


def test_no_arguments_prints_usage_and_returns_2(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["cli.py"])

    assert cli.main() == 2
    assert "Usage" in capsys.readouterr().out


def test_invalid_url_prints_error_and_returns_1(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["cli.py", "https://gitlab.com/pallets/flask"],
    )

    assert cli.main() == 1
    assert "Not a github.com URL" in capsys.readouterr().err