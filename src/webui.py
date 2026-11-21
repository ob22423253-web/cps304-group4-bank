"""Small local web gateway for the banking system (standard library only).

    python -m src.webui [--config run/cluster.json] [--port 8080]

The browser talks only to this gateway on 127.0.0.1. The gateway keeps one real encrypted client session
(X25519 + AES-256-GCM, the same protocol as the terminal client) per logged-in browser session and forwards the
actions to the coordinator. The browser never talks to a bank server directly.
"""
import argparse
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .client import BankClient
from .common import load_config, parse_amount
from .crypto import ConnectionClosed

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
ALLOWED = {"BALANCE", "HISTORY", "TRANSFER", "DEPOSIT", "WITHDRAW", "ADMIN_VIEW"}


class RecSock:
    """Wraps the client socket and remembers the last encrypted frame sent and received (for the wire panel)."""

    def __init__(self, sock):
        self._s, self.sent, self.recv_buf = sock, b"", b""

    def sendall(self, data):
        self.sent, self.recv_buf = data, b""
        return self._s.sendall(data)

    def recv(self, n):
        d = self._s.recv(n)
        self.recv_buf += d
        return d

    def __getattr__(self, name):
        return getattr(self._s, name)


def hexdump(b, limit=48):
    h = b[:limit].hex()
    h = " ".join(h[i:i + 2] for i in range(0, len(h), 2))
    return "%s%s  (%d bytes)" % (h, " ..." if len(b) > limit else "", len(b))


class Session:
    def __init__(self, client, rec):
        self.client, self.rec, self.lock = client, rec, threading.Lock()
        self.user = self.role = None
        self.accounts = []


class Gateway:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sessions = {}
        self.mu = threading.Lock()

    def new_client(self):
        c = BankClient.from_config(self.cfg).connect()
        rec = RecSock(c.conn.sock)
        c.conn.sock = rec
        return Session(c, rec)

    def call(self, sess, op, **kw):
        """Send one request over the encrypted session; returns (reply, wire info for the UI)."""
        plain = dict(op=op, **kw)
        shown = dict(plain)
        if "password" in shown:
            shown["password"] = "*" * len(shown["password"])
        with sess.lock:
            reply = sess.client.request(op, **kw)
            wire = {"plain": shown, "request_hex": hexdump(sess.rec.sent), "reply_hex": hexdump(sess.rec.recv_buf)}
        return reply, wire

    def login(self, user, password):
        try:
            sess = self.new_client()
            reply, wire = self.call(sess, "LOGIN", user=user, password=password)
        except (OSError, ConnectionClosed):
            return None, {"ok": False, "error": "bank coordinator is not reachable"}, None
        if not reply.get("ok"):
            sess.client.close()
            return None, reply, wire
        sess.user, sess.role, sess.accounts = user, reply["role"], reply["accounts"]
        sid = secrets.token_urlsafe(24)
        with self.mu:
            self.sessions[sid] = sess
        return sid, reply, wire

    def action(self, sess, body):
        op = str(body.get("op", "")).upper()
        if op not in ALLOWED:
            return {"ok": False, "error": "unknown action"}, None
        kw = {}
        try:
            for k in ("acct", "src", "dst"):
                if k in body:
                    kw[k] = str(body[k]).strip()
            if "amount" in body:
                kw["amount"] = parse_amount(str(body["amount"]))
            if op == "BALANCE":
                kw["consistency"] = "eventual" if body.get("consistency") == "eventual" else "strong"
            if op == "ADMIN_VIEW":
                kw["n"] = 12
            return self.call(sess, op, **kw)
        except ValueError:
            return {"ok": False, "error": "invalid amount (use e.g. 100 or 100.50)"}, None
        except (OSError, ConnectionClosed):
            return {"ok": False, "error": "connection to the bank was lost - please log in again", "relogin": True}, None


def make_server(cfg, port=8080, host="127.0.0.1"):
    gw = Gateway(cfg)

    class H(BaseHTTPRequestHandler):
        server_version = "BankUI"

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json", cookie=None):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):
            h = (self.headers.get("Host") or "").split(":")[0]
            return h in ("127.0.0.1", "localhost")

        def _sid(self):
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == "sid":
                    return v
            return None

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "bad host"})
            if self.path in ("/", "/index.html"):
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if self.path == "/api/me":
                s = gw.sessions.get(self._sid())
                return self._send(200, {"ok": bool(s), "user": s and s.user, "role": s and s.role, "accounts": s.accounts if s else []})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-UI") != "1":
                return self._send(403, {"ok": False, "error": "forbidden"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"ok": False, "error": "bad request"})
            if self.path == "/api/login":
                sid, reply, wire = gw.login(str(body.get("user", "")), str(body.get("password", "")))
                cookie = "sid=%s; HttpOnly; SameSite=Strict; Path=/" % sid if sid else None
                return self._send(200, dict(reply, wire=wire), cookie=cookie)
            sid = self._sid()
            sess = gw.sessions.get(sid)
            if self.path == "/api/logout":
                if sess:
                    sess.client.close()
                    gw.sessions.pop(sid, None)
                return self._send(200, {"ok": True}, cookie="sid=; Max-Age=0; Path=/")
            if self.path == "/api/action":
                if not sess:
                    return self._send(401, {"ok": False, "error": "please log in", "relogin": True})
                reply, wire = gw.action(sess, body)
                if reply.get("relogin"):
                    gw.sessions.pop(sid, None)
                return self._send(200, dict(reply, wire=wire))
            self._send(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), H)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="run/cluster.json")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()
    srv = make_server(load_config(a.config), a.port)
    print("Bank web UI on http://127.0.0.1:%d  (cluster config: %s)  Ctrl-C to stop" % (srv.server_address[1], a.config))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
