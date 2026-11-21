"""Web gateway: login ok, wrong password, role denied (real cluster, real encrypted session behind the gateway)."""
import json
import threading
import urllib.request
import urllib.error
import pytest
from src.webui import make_server


@pytest.fixture
def gateway(cluster):
    srv = make_server(cluster.cfg, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def post(base, path, body, cookie=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-UI": "1", **({"Cookie": cookie} if cookie else {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read()), r.headers.get("Set-Cookie")


def test_web_login_ok_and_encrypted_wire_info(gateway):
    r, cookie = post(gateway, "/api/login", {"user": "alice", "password": "Alice#2026"})
    assert r["ok"] and r["role"] == "customer" and "A-1001" in r["accounts"] and cookie.startswith("sid=")
    assert "Alice#2026" not in json.dumps(r["wire"])                 # password masked, frames are ciphertext
    b, _ = post(gateway, "/api/action", {"op": "BALANCE", "acct": "A-1001"}, cookie.split(";")[0])
    assert b["ok"] and b["balance"] == 1_000_000 and "A-1001" not in b["wire"]["request_hex"]


def test_web_wrong_password(gateway):
    r, cookie = post(gateway, "/api/login", {"user": "alice", "password": "nope"})
    assert r["ok"] is False and "invalid" in r["error"] and cookie is None


def test_web_role_denied_and_forged_request_rejected(gateway):
    r, cookie = post(gateway, "/api/login", {"user": "alice", "password": "Alice#2026"})
    d, _ = post(gateway, "/api/action", {"op": "DEPOSIT", "acct": "A-1001", "amount": "10"}, cookie.split(";")[0])
    assert d["ok"] is False and "access denied" in d["error"]
    req = urllib.request.Request(gateway + "/api/action", data=b"{}", headers={"Content-Type": "application/json"})   # no X-UI header
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 403
