"""Starts a real cluster and the web gateway, drives the page in a real (headless) browser with Playwright and saves
real screenshots to screenshots/ui_*.png.   Needs:  pip install playwright   and Google Chrome or Chromium installed."""
import os
import shutil
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from playwright.sync_api import sync_playwright          # noqa: E402
from src.cluster import Cluster                          # noqa: E402
from src.webui import make_server                        # noqa: E402

OUT = os.path.join(ROOT, "screenshots")


def browser_path():
    for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(n)
        if p:
            return p
    raise SystemExit("no Chrome/Chromium found - cannot make real screenshots")


def main():
    with Cluster() as c:
        srv = make_server(c.cfg, port=0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/" % srv.server_address[1]
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=browser_path(), headless=True, args=["--no-sandbox"])
            pg = b.new_page(viewport={"width": 1280, "height": 760}, device_scale_factor=1.5)
            shot = lambda name: pg.screenshot(path=os.path.join(OUT, name))

            pg.goto(url)
            pg.fill("#u", "alice"); pg.fill("#p", "wrong-password"); pg.click("#go")
            pg.wait_for_selector("#lmsg.err")
            shot("ui_01_login_wrong_password.png")

            pg.fill("#p", "Alice#2026"); pg.click("#go")
            pg.wait_for_function("document.getElementById('bal').textContent.startsWith('D')")
            pg.fill("#to", "B-2001"); pg.fill("#amt", "250.00"); pg.click("#bTr")
            pg.wait_for_function("document.getElementById('msg').textContent.includes('COMMITTED')", timeout=30000)
            pg.wait_for_function("document.querySelectorAll('#hist tr').length>1")
            shot("ui_02_customer_transfer_committed.png")

            pg.fill("#amt", "99999.00"); pg.click("#bTr")
            pg.wait_for_function("document.getElementById('msg').textContent.includes('ABORTED')", timeout=30000)
            shot("ui_03_transfer_aborted_insufficient_funds.png")

            pg.click(".tabs button[data-t=teller]"); pg.fill("#tAcct", "A-1001"); pg.fill("#tAmt", "10"); pg.click("#bDep")
            pg.wait_for_function("document.getElementById('msg').className.includes('deny')", timeout=30000)
            shot("ui_04_role_denied_customer_deposit.png")

            c.kill("B1")                                        # real SIGKILL of the Branch B primary
            pg.click(".tabs button[data-t=acct]"); pg.fill("#to", "B-2001"); pg.fill("#amt", "5.00"); pg.click("#bTr")
            pg.wait_for_function("document.getElementById('msg').textContent.includes('COMMITTED')", timeout=40000)
            pg.click("#logout"); pg.fill("#u", "admin"); pg.fill("#p", "Admin#2026"); pg.click("#go")
            pg.wait_for_selector("#t-acct", state="visible"); pg.click(".tabs button[data-t=admin]")
            pg.wait_for_selector("#nodes tr:nth-child(2)", timeout=30000)
            time.sleep(0.5)
            shot("ui_05_admin_status_after_primary_killed.png")
            b.close()
        srv.shutdown()
    print("UI screenshots written to", OUT)


if __name__ == "__main__":
    main()
