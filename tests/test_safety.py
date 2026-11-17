"""Defense in depth; static checks do not replace manual review."""

import ast
import importlib.metadata
import importlib.util
import sys
from pathlib import Path

from xbsis import __file__ as package_file

ROOT = Path(package_file).parent


def test_core_contains_no_sdk_import_or_execution_calls():
    forbidden_prefixes = ("order_", "orders_", "position_", "positions_")
    forbidden_calls = {
        "initialize",
        "login",
        "account_info",
        "history_deals_get",
        "history_orders_get",
    }
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != "MetaTrader5" for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "MetaTrader5"
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
                assert not name.startswith(forbidden_prefixes)
                assert name not in forbidden_calls
            assert not isinstance(node, ast.Call) or not (
                isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "__import__"}
            )


def test_linux_has_no_mt5_install_or_import():
    if sys.platform != "linux":
        return  # A Windows validation task may explicitly install the optional extra.
    assert importlib.util.find_spec("MetaTrader5") is None
    assert "MetaTrader5" not in sys.modules
    assert all(
        d.metadata["Name"].lower() != "metatrader5" for d in importlib.metadata.distributions()
    )


def test_gitignore_covers_sensitive_outputs_but_not_synthetic_fixture():
    import subprocess

    root = Path(__file__).resolve().parents[1]
    sensitive = [
        ".env",
        ".env.local",
        "local/quotes.json",
        "data/ticks.json",
        "datasets/ticks.json",
        "credentials.json",
        "secrets.json",
        "terminal/accounts.ini",
        "terminal/session.dat",
        "raw.parquet",
        "quotes.duckdb",
        "quotes.duckdb.wal",
        "terminal.log",
        "cookies.txt",
        "terminal.hst",
        "trading-token.txt",
        "key.pem",
        "quotes.jsonl",
        "raw.csv",
    ]
    result = subprocess.run(  # noqa: S603 -- fixed git ignore query with synthetic names
        ["git", "check-ignore", "--no-index", "--stdin"],  # noqa: S607
        input="\n".join(sensitive + ["src/xbsis/fixtures/quotes.json"]) + "\n",
        capture_output=True,
        text=True,
        cwd=root,
        check=True,
    )
    assert set(result.stdout.splitlines()) == set(sensitive)
