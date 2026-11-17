"""Real localhost HTTP/WebSocket smoke with spawned synthetic workers only."""

import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
PORT = 18765
ORIGIN = f"http://127.0.0.1:{PORT}"


def main() -> None:
    command = [sys.executable, "-m", "xbsis", "live-serve", "--port", str(PORT), "--duration", "15"]
    process = subprocess.Popen(  # noqa: S603 -- fixed interpreter and local synthetic command
        command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    opener = build_opener(ProxyHandler({}))
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                raise RuntimeError("synthetic server exited before readiness")
            try:
                with opener.open(ORIGIN + "/live/health", timeout=1) as response:  # noqa: S310
                    health = json.load(response)
                break
            except URLError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("synthetic server did not become ready") from None
                time.sleep(0.1)
        if health["mode"] != "MOCK":
            raise RuntimeError("unexpected server mode")
        for _ in range(2):
            with connect(f"ws://127.0.0.1:{PORT}/live/ws", origin=ORIGIN, proxy=None) as ws:
                deadline = time.monotonic() + 10
                while True:
                    data = json.loads(ws.recv(timeout=3))
                    if len(data["sources"]) == 2 and all(s["sequence"] for s in data["sources"]):
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("two synthetic workers did not publish")
                if [s["source_id"] for s in data["sources"]] != ["synthetic-1", "synthetic-2"]:
                    raise RuntimeError("source isolation mismatch")
                if [s["expected_account_environment"] for s in data["sources"]] != ["REAL", "DEMO"]:
                    raise RuntimeError("environment labels mismatch")
        try:
            with connect(
                f"ws://127.0.0.1:{PORT}/live/ws", origin="https://unrelated.example", proxy=None
            ):
                raise RuntimeError("unrelated WebSocket origin was accepted")
        except InvalidStatus as exc:
            if exc.response.status_code != 403:
                raise
        request = Request(  # noqa: S310 -- fixed loopback address
            ORIGIN + "/live/latest", headers={"Origin": "https://unrelated.example"}
        )
        try:
            opener.open(request, timeout=2)  # noqa: S310 -- fixed loopback origin
            raise RuntimeError("unrelated HTTP origin was accepted")
        except HTTPError as exc:
            if exc.code != 403:
                raise
        print("PASS: two mock workers, local HTTP, WebSocket, reconnect and origin rejection")
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError("synthetic server did not shut down in time") from None
        if process.stderr is not None:
            process.stderr.close()


if __name__ == "__main__":
    main()
