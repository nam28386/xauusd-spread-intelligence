"""Explicit commands only; default host is fixed loopback."""

import argparse
import hashlib
import json
from pathlib import Path

from xbsis.adapters.mock import MockBrokerAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description="XBSIS synthetic read-only Phase 01")
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("replay", help="replay packaged synthetic fixture")
    replay.add_argument("--output-dir", type=Path, help="optional local DuckDB/Parquet directory")
    serve = commands.add_parser("serve", help="serve only synthetic observations on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    from xbsis.mt5_cli import add_commands

    add_commands(commands)
    from xbsis.live_cli import add_live_command

    add_live_command(commands)
    args = parser.parse_args()
    if args.command == "live-serve":
        from xbsis.live_cli import run_live

        try:
            run_live(args)
        except ValueError as exc:
            parser.exit(2, f"Live error: {exc}\n")
        return
    if args.command in {"mt5-doctor", "mt5-capture"}:
        from xbsis.adapters.mt5 import MT5Error
        from xbsis.mt5_cli import run

        try:
            run(args)
        except MT5Error as exc:
            parser.exit(2, f"MT5 error: {exc}\n")
        except Exception:
            parser.exit(2, "MT5 error: operation failed; details suppressed for privacy.\n")
        return
    if args.command == "serve":
        import uvicorn

        if not 1 <= args.port <= 65535:
            parser.error("port must be between 1 and 65535")
        uvicorn.run(
            "xbsis.api:create_app", factory=True, host="127.0.0.1", port=args.port, access_log=False
        )
        return
    adapter = MockBrokerAdapter()
    records = adapter.replay()
    payload = "\n".join(record.model_dump_json() for record in records)
    if args.output_dir:
        from xbsis.storage import ObservationStore

        parquet = args.output_dir / "observations.parquet"
        if parquet.exists():
            parser.error("output already exists; choose a new output directory")
        with ObservationStore(args.output_dir / "observations.duckdb") as store:
            for record in records:
                store.append(record)
            store.export_parquet(parquet)
    print(
        json.dumps(
            {
                "mode": "MOCK_REPLAY",
                "records": len(records),
                "fixture_sha256": adapter.fixture_sha256,
                "observations_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
