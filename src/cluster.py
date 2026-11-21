"""Cluster launcher: seeds the databases and starts 7 OS processes (coordinator + 6 branch nodes).

Interactive use:   python -m src.cluster up [--dir run]
Programmatic use:  with Cluster() as c: ...
"""
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

from .client import BankClient
from .common import HOST, RpcError, rpc
from .crypto import new_identity
from .seed import PBKDF2_ITERATIONS, USERS, seed_all

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODES = ["A1", "A2", "B1", "B2", "C1", "C2"]


def free_ports(n):
    """n DISTINCT free ports: all sockets stay open until every port is known (no accidental reuse)."""
    socks = [socket.socket() for _ in range(n)]
    try:
        for s in socks:
            s.bind((HOST, 0))
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


class Cluster:
    def __init__(self, workdir=None, rpc_timeout=4.0, lock_timeout=1.5, pbkdf2_iterations=PBKDF2_ITERATIONS, keep=False):
        self.keep = keep or workdir is not None
        self.dir = os.path.abspath(workdir or tempfile.mkdtemp(prefix="cps304_"))
        self.rpc_timeout, self.lock_timeout, self.iters = rpc_timeout, lock_timeout, pbkdf2_iterations
        self.procs = {}
        self.cfg_path = os.path.join(self.dir, "cluster.json")
        self.cfg = None

    # ------------------------------------------------------------ lifecycle
    def start(self):
        if os.path.exists(self.dir):
            shutil.rmtree(self.dir)
        os.makedirs(os.path.join(self.dir, "logs"))
        seed_all(self.dir, self.iters)
        priv, pub = new_identity()
        from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
        with open(os.path.join(self.dir, "coordinator_identity.key"), "w") as f:
            f.write(priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex())
        ports = iter(free_ports(8))
        self.cfg = {
            "cluster_key": os.urandom(32).hex(), "data_dir": self.dir, "server_pub": pub.hex(),
            "coordinator": {"client_port": next(ports), "internal_port": next(ports)},
            "nodes": {b: {b + "1": next(ports), b + "2": next(ports)} for b in "ABC"},
            "rpc_timeout": self.rpc_timeout, "lock_timeout": self.lock_timeout, "seed": 304,
        }
        with open(self.cfg_path, "w") as f:
            json.dump(self.cfg, f, indent=1)
        for n in NODES:
            self._spawn(n)
        self._spawn("COORD")
        self.wait_ready()
        return self

    def _spawn(self, node, role=None):
        mod = "src.coordinator" if node == "COORD" else "src.branch"
        cmd = [sys.executable, "-m", mod, "--config", self.cfg_path]
        if node != "COORD":
            cmd += ["--node", node] + (["--role", role] if role else [])
        err = open(os.path.join(self.dir, "logs", node + ".err"), "a")
        self.procs[node] = subprocess.Popen(cmd, cwd=ROOT, stdout=err, stderr=err)

    def port(self, node):
        return self.cfg["coordinator"]["client_port"] if node == "COORD" else self.cfg["nodes"][node[0]][node]

    def wait_ready(self, nodes=None, timeout=20):
        end = time.time() + timeout
        for n in nodes or (NODES + ["COORD"]):
            while True:
                try:
                    socket.create_connection((HOST, self.port(n)), timeout=0.5).close()
                    break
                except OSError:
                    if time.time() > end:
                        raise RuntimeError("process %s did not start; see %s" % (n, self.dir))
                    time.sleep(0.05)

    def kill(self, node):
        p = self.procs.get(node)
        if p and p.poll() is None:
            p.kill()
        if p:
            p.wait()

    def restart(self, node, role=None):
        self.kill(node)
        self._spawn(node, role)
        self.wait_ready([node])

    def alive(self, node):
        return self.procs[node].poll() is None

    def wait_dead(self, node, timeout=10):
        end = time.time() + timeout
        while self.alive(node) and time.time() < end:
            time.sleep(0.05)
        return not self.alive(node)

    def stop(self):
        for n in list(self.procs):
            self.kill(n)
        if not self.keep:
            shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()

    # ------------------------------------------------------------ helpers for demos/tests
    def client(self, user, password=None, port=None):
        c = BankClient.from_config(self.cfg, port).connect()
        if user:
            r = c.login(user, password or USERS[user][0])
            assert r["ok"], r
        return c

    def node_rpc(self, node, msg, timeout=3):
        return rpc(self.port(node), msg, timeout, bytes.fromhex(self.cfg["cluster_key"]))

    def admin(self):
        return self.client("admin")

    def config(self, admin=None, flags=None, node_cfg=None, nodes=None):
        c = admin or self.admin()
        r = c.request("ADMIN_CONFIG", flags=flags or {}, node_cfg=node_cfg or {}, nodes=nodes)
        if admin is None:
            c.close()
        return r

    def db_balances(self, node):
        db = sqlite3.connect(os.path.join(self.dir, node + ".db"), timeout=10)
        try:
            return dict(db.execute("SELECT acct_id, balance FROM accounts").fetchall())
        finally:
            db.close()

    def total_from_db(self, nodes):
        return sum(sum(self.db_balances(n).values()) for n in nodes)

    def log_lines(self, node, pattern="", start=0):
        p = os.path.join(self.dir, "logs", node + ".log")
        if not os.path.exists(p):
            return []
        out = []
        for line in list(open(p))[start:]:
            if re.search(pattern, line):
                out.append(re.sub(r"^\d\d:\d\d:\d\d\.\d+ ", "", line.rstrip()))
        return out


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "up":
        print("usage: python -m src.cluster up [--dir run]")
        return
    d = sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv else os.path.join(ROOT, "run")
    c = Cluster(workdir=d).start()
    print("Cluster running (7 processes). Config: %s" % c.cfg_path)
    print("Start the client in another terminal:  python -m src.client --config %s" % c.cfg_path)
    print("Demo logins: alice/Alice#2026 (customer), teller1/Teller#2026 (teller), admin/Admin#2026 (admin)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        c.stop()


if __name__ == "__main__":
    main()
