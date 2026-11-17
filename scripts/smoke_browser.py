"""Linux browser smoke: synthetic live, sealed history, analytics and comparison."""

import json
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

from xbsis.adapters.mock import MockBrokerAdapter
from xbsis.sessions import SessionRecorder

ROOT = Path(__file__).resolve().parents[1]
PORT = 18767
ORIGIN = f"http://127.0.0.1:{PORT}"


def main():
    if sys.platform == "win32":
        raise SystemExit("Browser smoke is currently supported on Linux only.")
    executable = (
        shutil.which("chromium")
        or shutil.which("google-chrome")
        or shutil.which("google-chrome-stable")
    )
    if not executable:
        raise SystemExit("A locally installed Chromium/Chrome executable is required.")
    # One-point historical chart fixture; all values come from the synthetic fixture.
    single_name = "browser-single-" + uuid4().hex[:12]
    single = ROOT / "data" / "mt5" / single_name
    single.mkdir(parents=True, exist_ok=False)
    with SessionRecorder(single) as writer:
        writer.append(MockBrokerAdapter().replay()[0])
    command = [sys.executable, "-m", "xbsis", "live-serve", "--port", str(PORT), "--duration", "3"]
    process = subprocess.Popen(  # noqa: S603 -- fixed local synthetic invocation
        command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        deadline = time.monotonic() + 15
        while True:
            if process.poll() is not None:
                raise RuntimeError("local mock server exited")
            try:
                with opener.open(ORIGIN + "/live/latest", timeout=2) as response:  # noqa: S310
                    snapshot = json.load(response)
                if len(snapshot["sources"]) == 2 and all(
                    s["sequence"] for s in snapshot["sources"]
                ):
                    break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("mock workers did not become ready")
            time.sleep(0.1)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=executable,
                args=["--no-sandbox", "--disable-background-networking"],
            )
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors, external = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def route_request(route):
                if route.request.url.startswith(ORIGIN + "/"):
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()

            page.route("**/*", route_request)
            page.goto(ORIGIN + "/live/", wait_until="domcontentloaded")
            expect(page.locator("#socket-status")).to_have_text("CONNECTED", timeout=10000)
            expect(page.locator(".card")).to_have_count(2, timeout=10000)
            expect(page.locator(".state strong")).to_have_text(
                ["STOPPED", "STOPPED"], timeout=15000
            )
            with opener.open(ORIGIN + "/live/sources", timeout=2) as response:  # noqa: S310
                sources = json.load(response)
            first, second = [source["output_run"] for source in sources]
            page.locator('[data-tab="history"]').click()
            expect(page.locator('#history-session option[value="' + first + '"]')).to_have_count(1)
            page.locator("#history-session").select_option(first)
            page.locator("#history-load").click()
            expect(page.locator("#history-rows tr").first).to_be_visible(timeout=10000)
            page.locator("#history-session").select_option(single_name)
            page.locator("#history-load").click()
            expect(page.locator("#history-rows tr")).to_have_count(1, timeout=10000)
            page.locator('[data-tab="analytics"]').click()
            page.locator("#analytics-session").select_option(first)
            page.locator("#analytics-threshold").fill("0.25")
            page.locator("#analytics-run").click()
            expect(page.locator("#analytics-metrics .metric").first).to_be_visible(timeout=15000)
            expect(page.locator("#report-download")).to_be_visible()
            page.locator('[data-tab="compare"]').click()
            page.locator("#compare-left").select_option(first)
            page.locator("#compare-right").select_option(second)
            page.locator("#compare-threshold").fill("0.25")
            page.locator("#compare-run").click()
            expect(page.locator("#compare-metrics .metric").first).to_be_visible(timeout=15000)
            expect(page.locator("#compare-info")).to_contain_text("not equivalent")
            page.locator('[data-tab="realtime"]').click()
            expect(page.locator("#chart")).to_be_visible()
            page.locator('[data-tab="system"]').click()
            expect(page.locator("#system-detail")).to_contain_text("synthetic-1")
            if errors or external:
                raise RuntimeError("browser error or off-host request detected")
            browser.close()
        print("PASS: browser mock sources, one-point history, analytics, comparison and system")
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError("local mock server did not stop") from None
        if process.stderr:
            process.stderr.close()


if __name__ == "__main__":
    main()
