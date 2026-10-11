import sys

import pytest


def run(monkeypatch, *argv):
    from vault import cli

    monkeypatch.setattr(sys, "argv", ["vault", *argv])
    with pytest.raises(SystemExit) as e:
        cli.main()
    return e.value.code


def test_token_lifecycle(client, monkeypatch, capsys):
    assert run(monkeypatch, "token", "create", "phone") == 0
    out = capsys.readouterr().out
    assert len(out.split()[-1]) >= 40
    assert run(monkeypatch, "token", "list") == 0
    assert "phone" in capsys.readouterr().out
    assert run(monkeypatch, "token", "revoke", "phone") == 0


def test_import_prints_summary(client, monkeypatch, capsys, tmp_path):
    from conftest import png_bytes

    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.png").write_bytes(png_bytes())
    assert run(monkeypatch, "import", str(folder)) == 0
    assert "added 1" in capsys.readouterr().out
