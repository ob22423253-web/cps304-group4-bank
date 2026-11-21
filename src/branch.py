"""Branch server process: one SQLite DB, per-account locks, 2PC participant, WAL, replication.

Run:  python -m src.branch --config run/cluster.json --node A1 [--role backup]
Node ids: A1/B1/C1 start as primaries, A2/B2/C2 as hot standbys (a standby can be promoted).
"""
import argparse
import json
import os
import threading
import time

from .common import (HOST, Logger, RpcError, RpcTimeout, load_config, rpc, serve)
from .crypto import ConnectionClosed, SecurityError, server_handshake
from .locks import DeadlockVictim, LockManager, LockTimeout
from .wal import Store


class Branch:
    def __init__(self, cfg, node, role):
        self.cfg, self.node, self.role = cfg, node, role
        self.branch = node[0]
        self.psk = bytes.fromhex(cfg["cluster_key"])
        self.peer = self.branch + ("2" if node.endswith("1") else "1")
        self.port = cfg["nodes"][self.branch][node]
        self.peer_port = cfg["nodes"][self.branch][self.peer]
        self.log = Logger(os.path.join(cfg["data_dir"], "logs", node + ".log"), "%s:%s" % (node, role))
        self.store = Store(os.path.join(cfg["data_dir"], node + ".db"))
        self.locks = LockManager(log=self.log)
        # tunables (changed at run time through the CONFIG op, used by the demo / tests)
        self.ordered = False
        self.detect = True
        self.lock_timeout = cfg.get("lock_timeout", 1.5)
        self.step_delay = 0.0
        self.repl_delay = 0.0
        self.crash_at = ""
        self.hang_prepare = 0.0
        self.peer_acked = None
        self.ship_mu = threading.Lock()
        self.recovered = set()
        self.resolver_started = False
        self.stats = {"prepared": 0, "committed": 0, "aborted": 0, "no_votes": 0}

    # ------------------------------------------------------------ utilities
    def set_role(self, role):
        self.role = role
        self.log.name = "%s:%s" % (self.node, role)

    def failpoint(self, name):
        if self.crash_at == name:
            self.log("FAILPOINT '%s' reached -> process crashes now (os._exit, no cleanup)" % name)
            os._exit(137)

    def coordinator_rpc(self, msg):
        return rpc(self.cfg["coordinator"]["internal_port"], msg, 2.0, self.psk)

    # ------------------------------------------------------------ replication
    def replicate(self):
        if self.repl_delay > 0:
            self.log("replication delayed by %.1fs (lag injection)" % self.repl_delay)
            threading.Timer(self.repl_delay, self._ship).start()
        else:
            self._ship()

    def _ship(self):
        with self.ship_mu:
            try:
                if self.peer_acked is None:
                    self.peer_acked = rpc(self.peer_port, {"op": "REPL", "records": []}, 2.0, self.psk)["last"]
                for _ in range(4):
                    recs = self.store.records_after(self.peer_acked)
                    if not recs:
                        return
                    r = rpc(self.peer_port, {"op": "REPL", "records": recs}, 2.0, self.psk)
                    self.peer_acked = r["last"]
                    if r.get("ok"):
                        self.log("replicated WAL up to id %d to standby %s" % (self.peer_acked, self.peer))
                        return
            except RpcError as e:
                self.peer_acked = None
                self.log("standby %s unreachable (%s) - running without replica until it returns" % (self.peer, e))

    def op_repl(self, req):
        if self.role != "backup":
            return {"ok": False, "error": "not a backup"}
        with self.store.mu:
            last = self.store.last_wal_id()
            for r in req["records"]:
                if r["id"] <= last:
                    continue
                if r["id"] != last + 1:
                    return {"ok": False, "last": last}
                self.store.append(r["txid"], r["kind"], r["payload"], wal_id=r["id"], ts=r["ts"])
                last = r["id"]
        return {"ok": True, "last": last}

    # ------------------------------------------------------------ 2PC participant
    def _no(self, reason, retryable=False):
        self.stats["no_votes"] += 1
        return {"ok": True, "vote": "NO", "reason": reason, "retryable": retryable}

    def op_prepare(self, req):
        if self.role != "primary":
            return {"ok": False, "error": "not primary"}
        txid, ops = req["txid"], req["ops"]
        if self.hang_prepare:
            self.log("FAULT: hanging %.1fs before handling PREPARE %s" % (self.hang_prepare, txid))
            time.sleep(self.hang_prepare)
        st = self.store.tx_state(txid)
        if st in ("PREPARE", "COMMIT"):
            return {"ok": True, "vote": "YES", "note": "already " + st}
        if st == "ABORT":
            return self._no("already aborted")
        accts = []
        for o in ops:
            if o["acct"] not in accts:
                accts.append(o["acct"])
        if self.ordered:
            accts.sort()
        self.log("PREPARE %s: locking %s (%s order)" % (txid, accts, "sorted" if self.ordered else "request"))
        try:
            for a in accts:
                self.locks.acquire(txid, a, self.lock_timeout, self.detect)
                if self.step_delay:
                    time.sleep(self.step_delay)
        except DeadlockVictim:
            self.locks.release_all(txid)
            self.log("PREPARE %s: aborted as deadlock victim -> vote NO" % txid)
            return self._no("deadlock victim", retryable=True)
        except LockTimeout:
            self.locks.release_all(txid)
            self.log("PREPARE %s: lock timeout -> vote NO" % txid)
            return self._no("lock timeout", retryable=True)
        net = {}
        for o in ops:
            if self.store.balance(o["acct"]) is None:
                self.locks.release_all(txid)
                return self._no("unknown account " + o["acct"])
            net[o["acct"]] = net.get(o["acct"], 0) + o["delta"]
        for a, d in net.items():
            if self.store.balance(a) + d < 0:
                self.locks.release_all(txid)
                self.log("PREPARE %s: insufficient funds on %s -> vote NO" % (txid, a))
                return self._no("insufficient funds in " + a)
        self.store.append(txid, "PREPARE", json.dumps({"ops": ops}))
        self.stats["prepared"] += 1
        self.replicate()
        self.log("PREPARE %s: PREPARE record forced to WAL, vote YES" % txid)
        self.failpoint("after_prepare_log")
        return {"ok": True, "vote": "YES"}

    def op_commit(self, req):
        if self.role != "primary":
            return {"ok": False, "error": "not primary"}
        txid = req["txid"]
        self.failpoint("before_commit")
        st = self.store.tx_state(txid)
        if st == "COMMIT":
            return {"ok": True, "note": "already committed"}
        if st != "PREPARE":
            return {"ok": False, "error": "cannot commit tx in state %s" % st}
        self.store.append(txid, "COMMIT")
        self.failpoint("after_commit_log")
        self.locks.release_all(txid)
        self.stats["committed"] += 1
        self.log("COMMIT %s applied, locks released" % txid)
        self.replicate()
        return {"ok": True}

    def op_abort(self, req):
        if self.role != "primary":
            return {"ok": False, "error": "not primary"}
        txid = req["txid"]
        st = self.store.tx_state(txid)
        if st == "COMMIT":
            return {"ok": False, "error": "already committed"}
        if st != "ABORT":
            self.store.append(txid, "ABORT")
            self.stats["aborted"] += 1
            self.log("ABORT %s recorded, locks released" % txid)
            self.replicate()
        self.locks.release_all(txid)
        return {"ok": True}

    # ------------------------------------------------------------ recovery
    def recover(self):
        """Rebuild lock state from the WAL: every PREPAREd-but-undecided tx keeps its locks."""
        rows = self.store.in_doubt()
        for txid, _ in rows:
            accts = sorted({o["acct"] for o in self.store.prepared_ops(txid)})
            self.locks.force(txid, accts)
            self.recovered.add(txid)
            self.log("RECOVERY: tx %s is IN DOUBT (PREPARE logged, no outcome) - locks %s re-acquired" % (txid, accts))
        if not rows:
            self.log("RECOVERY: WAL scanned up to id %d, no in-doubt transactions" % self.store.last_wal_id())
        if not self.resolver_started:
            self.resolver_started = True
            threading.Thread(target=self._resolver, daemon=True).start()
        return [t for t, _ in rows]

    def _resolver(self):
        warned = set()
        while True:
            time.sleep(0.4)
            if self.role != "primary":
                continue
            for txid, ts in self.store.in_doubt():
                if txid not in self.recovered and time.time() - ts < 3.0:
                    continue
                try:
                    d = self.coordinator_rpc({"op": "DECISION", "txid": txid}).get("decision")
                except RpcError:
                    if txid not in warned:
                        warned.add(txid)
                        self.log("RECOVERY: coordinator unreachable, tx %s stays in doubt (will retry)" % txid)
                    continue
                if d == "COMMIT":
                    self.log("RECOVERY: coordinator says COMMIT for %s" % txid)
                    self.op_commit({"txid": txid})
                elif d == "ABORT":
                    self.log("RECOVERY: coordinator says ABORT for %s" % txid)
                    self.op_abort({"txid": txid})

    def op_promote(self, req):
        self.set_role("primary")
        self.peer_acked = None
        self.log("PROMOTED to primary (WAL up to id %d)" % self.store.last_wal_id())
        return {"ok": True, "in_doubt": self.recover()}

    # ------------------------------------------------------------ reads / admin
    def op_balance(self, req):
        b = self.store.balance(req["acct"])
        if b is None:
            return {"ok": False, "error": "unknown account"}
        return {"ok": True, "balance": b, "wal_id": self.store.last_wal_id(), "role": self.role, "node": self.node}

    def op_history(self, req):
        return {"ok": True, "history": self.store.history(req["acct"], req.get("n", 10))}

    def op_status(self, req):
        return {"ok": True, "node": self.node, "role": self.role, "wal_id": self.store.last_wal_id(),
                "total": self.store.total(), "in_doubt": [t for t, _ in self.store.in_doubt()],
                "locks": self.locks.snapshot(), "deadlocks": self.locks.deadlocks, "lock_timeouts": self.locks.timeouts,
                "stats": self.stats, "ordered": self.ordered, "detect": self.detect}

    def op_config(self, req):
        for k in ("ordered", "detect", "lock_timeout", "step_delay", "repl_delay", "crash_at", "hang_prepare"):
            if k in req:
                setattr(self, k, req[k])
        self.log("CONFIG %s" % {k: v for k, v in req.items() if k != "op"})
        return {"ok": True}

    # ------------------------------------------------------------ server loop
    def handle(self, req):
        fn = getattr(self, "op_" + str(req.get("op", "")).lower(), None)
        if fn is None:
            return {"ok": False, "error": "unknown op"}
        try:
            return fn(req)
        except Exception as e:
            self.log("ERROR in %s: %r" % (req.get("op"), e))
            return {"ok": False, "error": repr(e)}

    def connection(self, sock):
        try:
            conn = server_handshake(sock, psk=self.psk)
            conn.send(self.handle(conn.recv()))
        except (ConnectionClosed, SecurityError, OSError):
            pass

    def run(self):
        serve(self.port, self.connection)
        self.log("node up on port %d (role %s, peer %s)" % (self.port, self.role, self.peer))
        if self.role == "primary":
            self.recover()
        while True:
            time.sleep(3600)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--node", required=True)
    ap.add_argument("--role", default=None)
    a = ap.parse_args()
    role = a.role or ("primary" if a.node.endswith("1") else "backup")
    Branch(load_config(a.config), a.node, role).run()


if __name__ == "__main__":
    main()
