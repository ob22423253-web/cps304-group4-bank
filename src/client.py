"""Client library and menu-driven CLI.

Run:  python -m src.client --config run/cluster.json
"""
import argparse
import getpass
import socket
import sys
import time

from .common import HOST, fmt, load_config, parse_amount
from .crypto import ConnectionClosed, client_handshake


class BankClient:
    def __init__(self, port, server_pub_hex, host=HOST, timeout=15):
        self.addr, self.pub, self.timeout = (host, port), bytes.fromhex(server_pub_hex), timeout
        self.conn = None
        self.role = None
        self.accounts = []

    @classmethod
    def from_config(cls, cfg, port=None):
        return cls(port or cfg["coordinator"]["client_port"], cfg["server_pub"])

    def connect(self):
        s = socket.create_connection(self.addr, timeout=self.timeout)
        s.settimeout(self.timeout)
        self.conn = client_handshake(s, server_pub=self.pub)
        return self

    def request(self, op, **kw):
        self.conn.send(dict(op=op, **kw))
        return self.conn.recv()

    def login(self, user, password):
        r = self.request("LOGIN", user=user, password=password)
        if r.get("ok"):
            self.role, self.accounts = r["role"], r["accounts"]
        return r

    def close(self):
        if self.conn:
            self.conn.close()


# ------------------------------------------------------------------ CLI
MENU = """
  1) Balance            2) Deposit (teller)     3) Withdraw (teller)
  4) Transfer           5) History              6) Admin view (admin)
  7) Quit
"""


def _show(r):
    if r.get("ok"):
        return
    print("  ! %s" % r.get("error"))


def cli(client, inp=input):
    print("=== UTG Microfinance Unit - Secure Banking Client ===")
    for _ in range(3):
        user = inp("Username: ").strip()
        pw = inp("Password: ") if inp is not input else getpass.getpass("Password: ")
        r = client.login(user, pw)
        if r.get("ok"):
            break
        print("  ! %s" % r.get("error"))
    else:
        print("Too many failed attempts.")
        return
    print("Logged in as %s (role: %s). Your accounts: %s" % (user, client.role, ", ".join(client.accounts) or "-"))
    print("Session is protected by AES-256-GCM (key agreed with X25519 at login).")
    while True:
        print(MENU)
        c = inp("Choice> ").strip()
        try:
            if c == "1":
                a = inp("Account: ").strip()
                mode = inp("Read from (s)trong primary / (e)ventual replica [s]: ").strip().lower()
                r = client.request("BALANCE", acct=a, consistency="eventual" if mode == "e" else "strong")
                if r.get("ok"):
                    print("  Balance of %s: %s  [%s read from node %s, WAL position %s]" % (
                        a, fmt(r["balance"]), r["consistency"], r["node"], r["wal_id"]))
                _show(r)
            elif c in ("2", "3"):
                a = inp("Account: ").strip()
                amt = parse_amount(inp("Amount (D): "))
                r = client.request("DEPOSIT" if c == "2" else "WITHDRAW", acct=a, amount=amt)
                if r.get("txid"):
                    print("  %s (tx %s)" % (r["status"], r["txid"]))
                _show(r)
            elif c == "4":
                s = inp("From account: ").strip()
                d = inp("To account: ").strip()
                amt = parse_amount(inp("Amount (D): "))
                r = client.request("TRANSFER", src=s, dst=d, amount=amt)
                if r.get("txid"):
                    print("  %s (tx %s, attempts %d)" % (r["status"], r["txid"], r["attempts"]))
                _show(r)
            elif c == "5":
                a = inp("Account: ").strip()
                r = client.request("HISTORY", acct=a)
                for h in r.get("history", []):
                    print("  %-8s %12s  balance %12s  %s" % (h["txid"], fmt(h["delta"]), fmt(h["balance_after"]), h["memo"]))
                _show(r)
            elif c == "6":
                r = client.request("ADMIN_VIEW", n=6)
                if r.get("ok"):
                    print("  System total: %s   active nodes: %s" % (fmt(r["system_total"]), r["active"]))
                    for n, s in sorted(r["nodes"].items()):
                        print("   node %s role=%s wal=%s" % (n, s.get("role"), s.get("wal_id")))
                    for row in r["audit"]:
                        print("   audit #%d %-8s %-9s %-10s %s" % (row[0], row[2], row[3], row[4], row[6]))
                _show(r)
            elif c == "7":
                print("Goodbye.")
                return
            else:
                print("  ! choose 1-7")
        except ValueError:
            print("  ! invalid amount")
        except (ConnectionClosed, OSError):
            print("  ! connection lost")
            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="run/cluster.json")
    a = ap.parse_args()
    cl = BankClient.from_config(load_config(a.config)).connect()
    try:
        cli(cl)
    finally:
        cl.close()


if __name__ == "__main__":
    main()
