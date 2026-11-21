"""Transaction coordinator + secure client gateway.

* Client port: ECDH + Ed25519-signed handshake, AES-256-GCM frames, login with PBKDF2, role checks, audit log.
* Internal port: nodes ask for the outcome of in-doubt transactions (DECISION).
* Runs two-phase commit for every balance-changing operation, durable decision log,
  failover to a branch's hot standby, background delivery of undelivered decisions.

Run:  python -m src.coordinator --config run/cluster.json
"""
import argparse
import json
import os
import random
import threading
import time

from .common import (Logger, RpcError, RpcTimeout, RpcUnreachable, branch_of, fmt, load_config, rpc, serve)
from .crypto import (ConnectionClosed, ReplayError, SecurityError, TamperError, server_handshake, verify_password)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .seed import PBKDF2_ITERATIONS
from .wal import connect

PERMS = {
    "customer": {"BALANCE", "HISTORY", "TRANSFER"},
    "teller": {"BALANCE", "HISTORY", "TRANSFER", "DEPOSIT", "WITHDRAW"},
    "admin": {"BALANCE", "HISTORY", "ADMIN_VIEW", "ADMIN_CONFIG", "NODE_CONFIG"},
}


class Coordinator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.psk = bytes.fromhex(cfg["cluster_key"])
        self.rpc_timeout = cfg.get("rpc_timeout", 4.0)
        self.log = Logger(os.path.join(cfg["data_dir"], "logs", "coordinator.log"), "COORD")
        with open(os.path.join(cfg["data_dir"], "coordinator_identity.key")) as f:
            self.signer = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(f.read().strip()))
        self.db = connect(os.path.join(cfg["data_dir"], "coordinator.db"))
        self.mu = threading.RLock()
        self.fo_mu = threading.Lock()
        self.active = {b: b + "1" for b in cfg["nodes"]}
        self.flags = {"failover": True, "ordered": False, "commit_delay": 0.0, "max_retries": 6}
        self.inflight = set()
        self.stats = {"committed": 0, "aborted": 0, "retries": 0, "failovers": 0}
        self.owner = dict(self.db.execute("SELECT acct_id, owner FROM accounts").fetchall())
        r = self.db.execute("SELECT COALESCE(MAX(CAST(substr(txid,2) AS INTEGER)),0) FROM decisions").fetchone()[0]
        self.counter = r
        self.rng = random.Random(cfg.get("seed", 304))

    # ------------------------------------------------------------ helpers
    def audit(self, user, role, action, detail, outcome):
        with self.mu:
            self.db.execute("INSERT INTO audit(ts,username,role,action,detail,outcome) VALUES(?,?,?,?,?,?)",
                            (time.time(), user or "-", role or "-", action, detail, outcome))

    def new_txid(self):
        with self.mu:
            self.counter += 1
            return "T%06d" % self.counter

    def port_of(self, node):
        return self.cfg["nodes"][node[0]][node]

    @staticmethod
    def other(node):
        return node[0] + ("2" if node.endswith("1") else "1")

    # ------------------------------------------------------------ node calls and failover
    def call_node(self, node, msg, timeout=None):
        return rpc(self.port_of(node), msg, timeout or self.rpc_timeout, self.psk)

    def call_branch(self, branch, msg, failover=True):
        node = self.active[branch]
        try:
            return self.call_node(node, msg)
        except RpcTimeout:
            raise
        except RpcUnreachable:
            time.sleep(0.2)
        try:
            return self.call_node(node, msg)
        except RpcTimeout:
            raise
        except RpcUnreachable:
            if not (failover and self.flags["failover"]):
                raise
        self.do_failover(branch, node)
        return self.call_node(self.active[branch], msg)

    def do_failover(self, branch, failed):
        with self.fo_mu:
            if self.active[branch] != failed:
                return
            standby = self.other(failed)
            self.log("FAILOVER branch %s: %s unreachable -> promoting standby %s" % (branch, failed, standby))
            r = self.call_node(standby, {"op": "PROMOTE"})
            self.active[branch] = standby
            self.stats["failovers"] += 1
            self.log("FAILOVER branch %s complete: %s is now primary (in-doubt there: %s)" % (branch, standby, r.get("in_doubt")))
            self.audit("-", "system", "FAILOVER", "%s -> %s" % (failed, standby), "OK")

    # ------------------------------------------------------------ decision log + 2PC
    def log_decision(self, txid, decision, participants):
        with self.mu:
            self.db.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?,?)",
                            (txid, decision, json.dumps(participants), time.time()))

    def decision_for(self, txid):
        with self.mu:
            r = self.db.execute("SELECT decision FROM decisions WHERE txid=?", (txid,)).fetchone()
            if r:
                return r[0]
            if txid in self.inflight:
                return "PENDING"
            self.log_decision(txid, "ABORT", [])   # presumed abort: no decision was ever logged
            self.log("DECISION query for unknown tx %s -> presumed ABORT" % txid)
            return "ABORT"

    def deliver(self, txid, decision):
        """Send the decision to every participant that has not confirmed it yet."""
        with self.mu:
            row = self.db.execute("SELECT pending FROM decisions WHERE txid=?", (txid,)).fetchone()
        pending = json.loads(row[0]) if row else []
        for b in list(pending):
            try:
                r = self.call_branch(b, {"op": decision, "txid": txid})
                if r.get("ok"):
                    pending.remove(b)
                else:
                    self.log("%s %s at branch %s refused: %s" % (decision, txid, b, r.get("error")))
            except RpcError as e:
                self.log("%s %s: branch %s unreachable (%s) - decision stays pending" % (decision, txid, b, e))
        with self.mu:
            self.db.execute("UPDATE decisions SET pending=? WHERE txid=?", (json.dumps(pending), txid))
        return pending

    def pending_loop(self):
        while True:
            time.sleep(0.5)
            with self.mu:
                rows = self.db.execute("SELECT txid, decision FROM decisions WHERE pending != '[]'").fetchall()
            for txid, decision in rows:
                if txid not in self.inflight and self.deliver(txid, decision) == []:
                    self.log("pending %s %s finally delivered to all participants" % (decision, txid))

    def attempt(self, plan):
        txid = self.new_txid()
        with self.mu:
            self.inflight.add(txid)
        try:
            order = sorted(plan, key=lambda p: p[0]) if self.flags["ordered"] else list(plan)
            self.log("%s BEGIN participants=%s (%s order)" % (txid, [b for b, _ in order],
                                                              "global sorted" if self.flags["ordered"] else "request"))
            reason, retryable, touched = None, False, []
            for branch, ops in order:
                touched.append(branch)
                try:
                    r = self.call_branch(branch, {"op": "PREPARE", "txid": txid, "ops": ops})
                except RpcTimeout:
                    reason = "timeout waiting for branch %s" % branch
                    break
                except RpcError as e:
                    reason = "branch %s unreachable" % branch
                    break
                if not r.get("ok") or r.get("vote") != "YES":
                    reason, retryable = r.get("reason") or r.get("error"), bool(r.get("retryable"))
                    self.log("%s branch %s voted NO: %s" % (txid, branch, reason))
                    break
                self.log("%s branch %s voted YES" % (txid, branch))
            decision = "ABORT" if reason else "COMMIT"
            self.log_decision(txid, decision, touched)           # decision is durable BEFORE phase 2
            self.log("%s DECISION %s logged (participants %s)" % (txid, decision, touched))
            if decision == "COMMIT" and self.flags["commit_delay"]:
                time.sleep(self.flags["commit_delay"])
            pending = self.deliver(txid, decision)
        finally:
            with self.mu:
                self.inflight.discard(txid)
        out = {"txid": txid, "retryable": retryable, "reason": reason}
        if decision == "COMMIT":
            out["status"] = "COMMITTED_PENDING" if pending else "COMMITTED"
        else:
            out["status"] = "ABORTED"
        self.stats["committed" if decision == "COMMIT" else "aborted"] += 1
        return out

    def execute(self, plan):
        for n in range(1, self.flags["max_retries"] + 2):
            out = self.attempt(plan)
            out["attempts"] = n
            if out["status"] != "ABORTED" or not out["retryable"] or n > self.flags["max_retries"]:
                return out
            self.stats["retries"] += 1
            wait = self.rng.uniform(0.1, 0.4) * n
            self.log("%s aborted (%s) -> retry %d after %.2fs backoff" % (out["txid"], out["reason"], n, wait))
            time.sleep(wait)

    # ------------------------------------------------------------ client operations
    def result(self, out):
        ok = out["status"] in ("COMMITTED", "COMMITTED_PENDING")
        r = {"ok": ok, "txid": out["txid"], "status": out["status"], "attempts": out["attempts"]}
        if not ok:
            r["error"] = out["reason"]
        return r

    def op_balance(self, req, sess):
        acct = req["acct"]
        b = branch_of(acct)
        if req.get("consistency", "strong") == "eventual":
            r = self.call_node(self.other(self.active[b]), {"op": "BALANCE", "acct": acct})
        else:
            r = self.call_branch(b, {"op": "BALANCE", "acct": acct})
        if r.get("ok"):
            r["consistency"] = req.get("consistency", "strong")
        return r

    def op_history(self, req, sess):
        return self.call_branch(branch_of(req["acct"]), {"op": "HISTORY", "acct": req["acct"]})

    def op_deposit(self, req, sess):
        a = req["acct"]
        return self.result(self.execute([(branch_of(a), [{"acct": a, "delta": req["amount"], "memo": "cash deposit"}])]))

    def op_withdraw(self, req, sess):
        a = req["acct"]
        return self.result(self.execute([(branch_of(a), [{"acct": a, "delta": -req["amount"], "memo": "cash withdrawal"}])]))

    def op_transfer(self, req, sess):
        s, d, amt = req["src"], req["dst"], req["amount"]
        out = {"acct": s, "delta": -amt, "memo": "transfer to " + d}
        inn = {"acct": d, "delta": amt, "memo": "transfer from " + s}
        plan = [(branch_of(s), [out, inn])] if branch_of(s) == branch_of(d) else [(branch_of(s), [out]), (branch_of(d), [inn])]
        return self.result(self.execute(plan))

    def all_status(self):
        res = {}
        for b in self.cfg["nodes"]:
            for n in self.cfg["nodes"][b]:
                try:
                    res[n] = self.call_node(n, {"op": "STATUS"}, 1.5)
                except RpcError:
                    res[n] = {"ok": False, "role": "DOWN"}
        return res

    def op_admin_view(self, req, sess):
        st = self.all_status()
        total = sum(st[self.active[b]].get("total", 0) for b in self.active if st[self.active[b]].get("ok"))
        with self.mu:
            rows = self.db.execute("SELECT id,ts,username,role,action,detail,outcome FROM audit ORDER BY id DESC LIMIT ?",
                                   (req.get("n", 12),)).fetchall()
        return {"ok": True, "nodes": st, "active": self.active, "system_total": total, "flags": self.flags,
                "stats": self.stats, "audit": [list(r) for r in rows][::-1]}

    def op_admin_config(self, req, sess):
        self.flags.update(req.get("flags", {}))
        nc = dict(req.get("node_cfg", {}))
        if "ordered" in self.flags and "ordered" not in nc:
            nc["ordered"] = self.flags["ordered"]
        nc["op"] = "CONFIG"
        for n in req.get("nodes") or [n for b in self.cfg["nodes"] for n in self.cfg["nodes"][b]]:
            try:
                self.call_node(n, nc, 1.5)
            except RpcError:
                pass
        return {"ok": True, "flags": self.flags}

    def op_node_config(self, req, sess):
        c = dict(req["cfg"])
        c["op"] = "CONFIG"
        return self.call_node(req["node"], c, 2.0)

    # ------------------------------------------------------------ login / dispatch
    def do_login(self, req, sess):
        u, pw = req.get("user", ""), req.get("password", "")
        with self.mu:
            row = self.db.execute("SELECT salt,pw_hash,iterations,role FROM users WHERE username=?", (u,)).fetchone()
        ok = bool(row) and verify_password(pw, row[0], row[1], row[2])
        if not ok:
            if not row:   # equalise timing for unknown users
                verify_password(pw, "00" * 16, "00" * 32, PBKDF2_ITERATIONS)
            sess["fails"] += 1
            self.audit(u, None, "LOGIN", "bad credentials", "FAILED")
            return {"ok": False, "error": "invalid username or password", "close": sess["fails"] >= 3}
        sess["user"], sess["role"] = u, row[3]
        accts = [a for a, o in self.owner.items() if o == u]
        self.audit(u, row[3], "LOGIN", "session established", "OK")
        return {"ok": True, "role": row[3], "accounts": accts}

    def dispatch(self, req, sess):
        op = str(req.get("op", "")).upper()
        if op == "LOGIN":
            return self.do_login(req, sess)
        user, role = sess["user"], sess["role"]
        if not user:
            self.audit(None, None, op, "not logged in", "DENIED")
            return {"ok": False, "error": "login required"}
        if op not in PERMS[role]:
            self.audit(user, role, op, json.dumps({k: v for k, v in req.items() if k != "op"}), "DENIED")
            return {"ok": False, "error": "access denied: role '%s' may not perform %s" % (role, op)}
        acct_keys = [req[k] for k in ("acct", "src") if k in req]
        for a in acct_keys + ([req["dst"]] if "dst" in req else []):
            if a not in self.owner:
                return {"ok": False, "error": "unknown account " + str(a)}
        if role == "customer" and any(self.owner[a] != user for a in acct_keys):
            self.audit(user, role, op, "account not owned: %s" % acct_keys, "DENIED")
            return {"ok": False, "error": "access denied: account belongs to another customer"}
        if op in ("DEPOSIT", "WITHDRAW", "TRANSFER"):
            if not isinstance(req.get("amount"), int) or req["amount"] <= 0:
                return {"ok": False, "error": "amount must be a positive integer number of bututs"}
            if op == "TRANSFER" and req["src"] == req["dst"]:
                return {"ok": False, "error": "source and destination are the same account"}
        try:
            r = getattr(self, "op_" + op.lower())(req, sess)
        except RpcError as e:
            r = {"ok": False, "error": "branch unavailable: %s" % e}
        detail = json.dumps({k: v for k, v in req.items() if k != "op"})
        self.audit(user, role, op, detail + (" -> " + r["txid"] if r.get("txid") else ""),
                   r.get("status") or ("OK" if r.get("ok") else "ERROR: %s" % r.get("error")))
        return r

    def client_connection(self, sock):
        sess = {"user": None, "role": None, "fails": 0}
        try:
            conn = server_handshake(sock, signer=self.signer)
        except (SecurityError, ConnectionClosed, OSError):
            return
        while True:
            try:
                req = conn.recv()
            except ConnectionClosed:
                return
            except (TamperError, ReplayError) as e:
                kind = "REPLAY" if isinstance(e, ReplayError) else "TAMPER"
                self.audit(sess["user"], sess["role"], "SECURITY", "%s detected: %s" % (kind, e), "REJECTED")
                self.log("SECURITY %s from user=%s: %s - connection dropped" % (kind, sess["user"], e))
                return
            except OSError:
                return
            try:
                resp = self.dispatch(req, sess)
            except Exception as e:
                self.log("ERROR %r" % e)
                resp = {"ok": False, "error": "internal error"}
            try:
                conn.send(resp)
            except OSError:
                return
            if resp.get("close"):
                return

    def internal_connection(self, sock):
        try:
            conn = server_handshake(sock, psk=self.psk)
            req = conn.recv()
            if req.get("op") == "DECISION":
                d = self.decision_for(req["txid"])
                self.log("node asked outcome of %s -> %s" % (req["txid"], d))
                conn.send({"ok": True, "decision": d})
            else:
                conn.send({"ok": False})
        except (ConnectionClosed, SecurityError, OSError):
            pass

    def run(self):
        serve(self.cfg["coordinator"]["client_port"], self.client_connection)
        serve(self.cfg["coordinator"]["internal_port"], self.internal_connection)
        threading.Thread(target=self.pending_loop, daemon=True).start()
        self.log("coordinator up (client port %d)" % self.cfg["coordinator"]["client_port"])
        while True:
            time.sleep(3600)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    Coordinator(load_config(ap.parse_args().config)).run()


if __name__ == "__main__":
    main()
