"""CLI validation and localhost-only startup for the live dashboard."""

import sys
from pathlib import Path

from xbsis.live_config import load_local_sources


def add_live_command(commands):
    parser = commands.add_parser("live-serve", help="local observation dashboard")
    parser.add_argument("--mode", choices=("mock", "mt5"), default="mock")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--sources-file", type=Path)
    parser.add_argument("--confirm-live-readonly", action="store_true")
    parser.add_argument("--duration", type=int, default=120)


def mock_sources():
    return [
        {
            "source_id": f"synthetic-{i + 1}",
            "broker_id": f"synthetic-broker-{i + 1}",
            "server_alias": f"synthetic-server-{i + 1}",
            "expected_account_environment": "REAL" if i == 0 else "DEMO",
            "account_type_user_label": "UNKNOWN",
            "symbol": "XAUUSD.mock",
        }
        for i in range(2)
    ]


def run_live(args):
    if not 1 <= args.port <= 65535 or not 1 <= args.duration <= 28_800:
        raise ValueError("Port must be 1–65535 and duration 1–28800 seconds.")
    if args.mode == "mt5":
        if sys.platform != "win32":
            raise ValueError("MT5 live mode requires local Windows; cloud must use mock.")
        if not args.confirm_live_readonly or args.sources_file is None:
            raise ValueError("MT5 mode requires a local sources file and --confirm-live-readonly.")
        sources = [s.model_dump(mode="json") for s in load_local_sources(args.sources_file).sources]
    else:
        if args.sources_file is not None or args.confirm_live_readonly:
            raise ValueError("Mock mode does not accept a live sources file or live confirmation.")
        sources = mock_sources()
    import uvicorn

    from xbsis.live_api import create_live_app

    app = create_live_app(args.mode, sources, args.duration, args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, reload=False, access_log=False)
