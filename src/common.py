"""Shared helpers: config, RPC over the secure channel, server loop, logging, money formatting."""
import json
import socket
import threading
import time

from .crypto import ConnectionClosed, SecurityError, client_handshake

HOST = "127.0.0.1"


class RpcError(Exception):
    pass


class RpcTimeout(RpcError):
    pass


class RpcUnreachable(RpcError):
    pass


def load_config(path):
    with open(path) as f:
        return json.load(f)


def branch_of(acct):
    return acct.split("-")[0]


def fmt(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return "%sD %s.%02d" % (sign, format(cents // 100, ","), cents % 100)


def parse_amount(text):
    """'100.50' -> 10050 (integer bututs). Raises ValueError on bad input."""
    d, _, c = text.strip().partition(".")
    if not d.isdigit() or (c and (not c.isdigit() or len(c) > 2)):
        raise ValueError("invalid amount")
    return int(d) * 100 + int((c + "00")[:2])


def rpc(port, msg, timeout, psk, host=HOST):
    """One request/response over a fresh PSK-authenticated encrypted connection."""
    s = None
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.settimeout(timeout)
        conn = client_handshake(s, psk=psk)
        conn.send(msg)
        return conn.recv()
    except socket.timeout:
        raise RpcTimeout("timeout talking to port %d" % port)
    except (OSError, ConnectionClosed, SecurityError) as e:
        raise RpcUnreachable("%s: %s" % (type(e).__name__, e))
    finally:
        if s:
            try:
                s.close()
            except OSError:
                pass


def serve(port, handler, host=HOST):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(256)

    def run(c):
        try:
            handler(c)
        except Exception:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=run, args=(c,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv


class Logger:
    def __init__(self, path, name):
        self.path, self.name, self.mu = path, name, threading.Lock()

    def __call__(self, msg):
        t = time.time()
        line = "%s.%03d [%s] %s\n" % (time.strftime("%H:%M:%S", time.localtime(t)), int(t * 1000) % 1000, self.name, msg)
        with self.mu:
            with open(self.path, "a") as f:
                f.write(line)
