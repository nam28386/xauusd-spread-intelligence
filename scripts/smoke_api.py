"""Start the real CLI, verify local HTTP behavior, then stop only our process."""

import json
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

# Fixed loopback destinations; never send local requests through an external proxy.
LOCAL_ORIGIN = "http://127.0.0.1:18761"


def main() -> None:
    command = [sys.executable, "-m", "xbsis", "serve", "--port", "18761"]
    process = subprocess.Popen(command)  # noqa: S603 -- fixed local interpreter and arguments
    opener = build_opener(ProxyHandler({}))
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                raise RuntimeError("local API exited before readiness")
            try:
                with opener.open(LOCAL_ORIGIN + "/health", timeout=1) as response:  # noqa: S310
                    health = json.load(response)
                break
            except URLError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("local API did not become ready") from None
                time.sleep(0.1)
        if health != {"status": "ok", "mode": "MOCK_REPLAY", "live_connectivity": "NOT_TESTED"}:
            raise RuntimeError("unexpected health contract")
        with opener.open(LOCAL_ORIGIN + "/v1/quotes?limit=2", timeout=2) as response:  # noqa: S310
            records = json.load(response)
        if len(records) != 2 or records[0]["spread"]["spread_usd_per_oz"] != "0.25000":
            raise RuntimeError("unexpected synthetic quote response")
        if records[1]["spread"]["data_quality_flags"] != ["DUPLICATE"]:
            raise RuntimeError("quality flags missing from response")
        print(
            "PASS: localhost HTTP health, synthetic spread, duplicate provenance; "
            "no live connection"
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
