import sys

import pytest
import uvicorn

from xbsis.__main__ import main


def test_serve_command_always_uses_loopback(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["xbsis", "serve"])
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    main()
    assert calls == [
        (
            ("xbsis.api:create_app",),
            {
                "factory": True,
                "host": "127.0.0.1",
                "port": 8000,
                "access_log": False,
            },
        )
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        ["serve", "--host", "0.0.0.0"],  # noqa: S104 -- negative test: CLI rejects public bind
        ["serve", "--port", "0"],
        ["serve", "--port", "65536"],
        ["live"],
    ],
)
def test_unsafe_or_invalid_cli_arguments_rejected(monkeypatch, arguments):
    monkeypatch.setattr(sys, "argv", ["xbsis", *arguments])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_cli_explicit_export_does_not_overwrite(tmp_path, monkeypatch, capsys):
    output = tmp_path / "synthetic-run"
    monkeypatch.setattr(sys, "argv", ["xbsis", "replay", "--output-dir", str(output)])
    main()
    capsys.readouterr()
    parquet = output / "observations.parquet"
    original = parquet.read_bytes()
    assert (output / "observations.duckdb").is_file()
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert parquet.read_bytes() == original
