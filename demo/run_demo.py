"""Runs every demo scenario automatically and saves the labelled output to demo/output/*.txt.

    python demo/run_demo.py            # all scenarios
    python demo/run_demo.py 5 6        # selected scenarios
"""
import contextlib
import io
import os
import random
import re
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.client import BankClient, cli                                   # noqa: E402
from src.cluster import Cluster                                          # noqa: E402
from src.common import fmt                                               # noqa: E402
from src.netproxy import MitmProxy                                       # noqa: E402
from src.seed import ALL_ACCOUNTS, SYSTEM_TOTAL                          # noqa: E402
from src.wal import Store                                                # noqa: E402

OUT_DIR = os.path.join(ROOT, "demo", "output")
PRIMARIES, STANDBYS = ["A1", "B1", "C1"], ["A2", "B2", "C2"]
RESULTS = []


class Out:
    def __init__(self, fname, title):
        self.fname, self.lines = fname, []
        self.bar("=")
        self.p(title)
        self.bar("=")

    def p(self, *a):
        s = " ".join(str(x) for x in a)
        print(s, flush=True)
        self.lines.append(s)

    def bar(self, ch="-"):
        self.p(ch * 78)

    def h(self, t):
        self.p("")
        self.p(">>> " + t)

    def check(self, cond, msg):
        RESULTS.append(bool(cond))
        self.p("  [%s] %s" % ("PASS" if cond else "FAIL", msg))

    def logs(self, c, node, pattern, start=None):
        for l in c.log_lines(node, pattern, (start or {}).get(node, 0)):
            self.p("    log| " + l)

    def save(self):
        with open(os.path.join(OUT_DIR, self.fname), "w") as f:
            f.write("\n".join(self.lines) + "\n")


def mark(c):
    return {n: len(c.log_lines(n)) for n in ("A1", "B1", "coordinator")}


def bals(c, accts, nodes=PRIMARIES):
    d = {}
    for n in nodes:
        d.update(c.db_balances(n))
    return {a: d[a] for a in accts}


def show_bal(o, c, accts, nodes=PRIMARIES, label=""):
    b = bals(c, accts, nodes)
    o.p("    %s%s" % (label, "   ".join("%s=%s" % (a, fmt(v)) for a, v in b.items())))


def wal_rows(c, node):
    return [(r["id"], r["txid"], r["kind"]) for r in Store(os.path.join(c.dir, node + ".db")).records_after(0)]


def total(c, nodes=PRIMARIES):
    return c.total_from_db(nodes)


def run_pair(c, first, second, amt=10000, stagger=0.1):
    res = [None, None]

    def w(i, s, d):
        cl = c.client("teller1")
        res[i] = cl.request("TRANSFER", src=s, dst=d, amount=amt)
        cl.close()
    ts = [threading.Thread(target=w, args=(0, *first))]
    ts[0].start()
    time.sleep(stagger)
    ts.append(threading.Thread(target=w, args=(1, *second)))
    ts[1].start()
    [t.join() for t in ts]
    return res


# ---------------------------------------------------------------- scenarios
def s01():
    o = Out("01_normal_transfer.txt", "SCENARIO 1 - Normal cross-branch transfer (2PC commit): A-1001 (Branch A) -> B-2001 (Branch B), D 250.00")
    with Cluster() as c:
        t = c.client("teller1")
        o.h("Initial state (primary DBs)")
        show_bal(o, c, ["A-1001", "B-2001"])
        o.p("    system total = %s" % fmt(total(c)))
        o.h("Teller transfers D 250.00 over the encrypted channel")
        r = t.request("TRANSFER", src="A-1001", dst="B-2001", amount=25000)
        o.p("    reply:", r)
        o.h("Coordinator log (2PC phases)")
        o.logs(c, "coordinator", r["txid"])
        o.h("Participant logs")
        o.logs(c, "A1", r["txid"])
        o.logs(c, "B1", r["txid"])
        o.h("Write-ahead logs on the primaries (id, txid, record)")
        o.p("    A1:", wal_rows(c, "A1"))
        o.p("    B1:", wal_rows(c, "B1"))
        o.h("Final state")
        show_bal(o, c, ["A-1001", "B-2001"], label="primaries: ")
        show_bal(o, c, ["A-1001", "B-2001"], STANDBYS, label="standbys : ")
        o.p("    system total = %s" % fmt(total(c)))
        o.check(r["status"] == "COMMITTED", "transaction committed on both branches")
        o.check(bals(c, ["A-1001"])["A-1001"] == 975000 and bals(c, ["B-2001"])["B-2001"] == 1025000, "debit and credit both applied (D 9,750.00 / D 10,250.00)")
        o.check(total(c) == SYSTEM_TOTAL, "total money unchanged (%s)" % fmt(SYSTEM_TOTAL))
        o.check(bals(c, ["A-1001", "B-2001"], STANDBYS) == bals(c, ["A-1001", "B-2001"]), "hot standbys hold identical balances (replication)")
    o.save()


def s02():
    o = Out("02_insufficient_funds.txt", "SCENARIO 2 - Insufficient funds: 2PC aborts, nothing changes")
    with Cluster() as c:
        t = c.client("teller1")
        before = {n: c.db_balances(n) for n in PRIMARIES}
        o.h("Teller tries to move D 99,999.00 from A-1001 (balance D 10,000.00) to B-2001")
        r = t.request("TRANSFER", src="A-1001", dst="B-2001", amount=9_999_900)
        o.p("    reply:", r)
        o.logs(c, "coordinator", r["txid"])
        o.logs(c, "A1", r["txid"])
        o.h("State after the abort")
        o.p("    A1 WAL:", wal_rows(c, "A1"), "  B1 WAL:", wal_rows(c, "B1"))
        o.p("    locks held on A1:", c.node_rpc("A1", {"op": "STATUS"})["locks"])
        o.check(r["status"] == "ABORTED" and "insufficient" in r["error"], "transaction aborted with reason: %s" % r.get("error"))
        o.check({n: c.db_balances(n) for n in PRIMARIES} == before, "every balance on every branch is unchanged")
        o.check(c.node_rpc("A1", {"op": "STATUS"})["locks"] == {}, "no locks left behind")
        o.check(not wal_rows(c, "B1"), "Branch B never even prepared (sequential prepare stopped at the first NO vote)")
        o.check(total(c) == SYSTEM_TOTAL, "total money unchanged")
    o.save()


def s03():
    o = Out("03_participant_crash_recovery.txt", "SCENARIO 3 - Participant crashes during 2PC and recovers from its write-ahead log")
    with Cluster() as c:
        t = c.client("teller1")
        c.config(flags={"failover": False})
        o.h("3a) Branch B primary crashes right AFTER forcing its PREPARE record (before replying to the coordinator)")
        c.config(nodes=["B1"], node_cfg={"crash_at": "after_prepare_log"})
        r = t.request("TRANSFER", src="A-1001", dst="B-2001", amount=10000)
        c.wait_dead("B1")
        o.p("    coordinator reply:", r)
        o.p("    B1 process alive?", c.alive("B1"))
        o.p("    B1 WAL on disk:", wal_rows(c, "B1"), " -> PREPARE without COMMIT/ABORT = IN DOUBT")
        o.h("Restarting B1 (it only has its disk: SQLite + WAL)")
        c.restart("B1")
        end = time.time() + 10
        while (lambda st: st["in_doubt"] or st["locks"])(c.node_rpc("B1", {"op": "STATUS"})) and time.time() < end:
            time.sleep(0.2)
        o.logs(c, "B1", "RECOVERY: tx")
        o.p("    B1 WAL after recovery:", wal_rows(c, "B1"))
        o.check(r["status"] == "ABORTED", "coordinator aborted the transfer (no vote from B1)")
        o.check(c.node_rpc("B1", {"op": "STATUS"})["in_doubt"] == [] and wal_rows(c, "B1")[-1][2] == "ABORT", "in-doubt transaction resolved as ABORT after asking the coordinator")
        o.check(bals(c, ["A-1001"])["A-1001"] == 1_000_000 and bals(c, ["B-2001"])["B-2001"] == 1_000_000, "balances unchanged on both branches")
        o.check(c.node_rpc("B1", {"op": "STATUS"})["locks"] == {}, "locks of the in-doubt transaction released")

        o.h("3b) Branch B primary crashes when the COMMIT message arrives (decision is already COMMIT)")
        c.config(nodes=["B1"], node_cfg={"crash_at": "before_commit"})
        r = t.request("TRANSFER", src="A-1001", dst="B-2001", amount=10000)
        c.wait_dead("B1")
        o.p("    coordinator reply:", r, " (decision durable, B1 not yet updated)")
        show_bal(o, c, ["A-1001"], label="A: ")
        o.p("    B1 DB (dead node, read from disk): B-2001 = %s   <- credit not applied yet" % fmt(c.db_balances("B1")["B-2001"]))
        o.p("    total money visible right now = %s (money is 'in flight', not lost)" % fmt(total(c)))
        c.restart("B1")
        end = time.time() + 10
        while c.db_balances("B1")["B-2001"] != 1_010_000 and time.time() < end:
            time.sleep(0.2)
        o.h("After restart")
        o.logs(c, "B1", "T000002")
        show_bal(o, c, ["A-1001", "B-2001"])
        o.check(r["status"] == "COMMITTED_PENDING", "client told COMMITTED_PENDING (outcome is final, delivery pending)")
        o.check(c.db_balances("B1")["B-2001"] == 1_010_000, "recovered B1 applied the COMMIT from its WAL decision")
        o.check(total(c) == SYSTEM_TOTAL, "total money unchanged after recovery")
    o.save()


def s04():
    o = Out("04_primary_failover.txt", "SCENARIO 4 - Primary killed between PREPARE and COMMIT: coordinator fails over to the hot standby")
    with Cluster() as c:
        t = c.client("teller1")
        c.config(flags={"commit_delay": 1.5})
        o.h("Transfer D 300.00 A-1001 -> B-2001; coordinator pauses 1.5 s after logging COMMIT so we can kill B1 in the window")
        out = {}
        th = threading.Thread(target=lambda: out.update(t.request("TRANSFER", src="A-1001", dst="B-2001", amount=30000)))
        th.start()
        time.sleep(0.8)
        o.p("    B1 WAL now:", wal_rows(c, "B1"), "(B1 voted YES and is PREPARED)")
        o.p("    B2 (standby) WAL now:", wal_rows(c, "B2"), "(PREPARE already replicated)")
        o.p("    >>> kill -9 B1 (process.kill)")
        c.kill("B1")
        th.join(30)
        o.p("    client reply:", out)
        o.h("Coordinator and standby logs")
        o.logs(c, "coordinator", "FAILOVER|T000001 ")
        o.logs(c, "B2", "PROMOTED|COMMIT|RECOVERY")
        v = c.admin().request("ADMIN_VIEW")
        o.p("    active node per branch:", v["active"])
        show_bal(o, c, ["A-1001", "B-2001"], nodes=["A1", "B2"], label="state: ")
        o.p("    system total (active nodes) = %s" % fmt(v["system_total"]))
        o.h("Service continues on the new primary; old primary B1 is restarted as a standby and catches up")
        r2 = t.request("DEPOSIT", acct="B-2002", amount=500)
        o.p("    deposit D 5.00 to B-2002 on B2:", r2["status"])
        c.restart("B1", role="backup")
        t.request("DEPOSIT", acct="B-2002", amount=500)
        time.sleep(0.5)
        o.p("    B1 (rejoined) balances == B2:", c.db_balances("B1") == c.db_balances("B2"), "| B1 WAL:", wal_rows(c, "B1"))
        o.check(out.get("status") == "COMMITTED", "transfer committed although a participant primary was killed mid-transaction")
        o.check(v["active"]["B"] == "B2", "coordinator switched Branch B to the standby")
        o.check(c.db_balances("B2")["B-2001"] == 1_030_000 and c.db_balances("A1")["A-1001"] == 970_000, "debit and credit both applied exactly once")
        o.check(v["system_total"] == SYSTEM_TOTAL, "total money unchanged")
        o.check(c.db_balances("B1") == c.db_balances("B2"), "restarted old primary re-synchronised from the new primary")
    o.save()


def s05():
    o = Out("05_deadlock_detected.txt", "SCENARIO 5 - Deadlock WITHOUT lock ordering: real deadlock, detection, victim abort, retry")
    pair = (("A-1001", "A-1002"), ("A-1002", "A-1001"))
    with Cluster() as c:
        o.p("T1: transfer A-1001 -> A-1002 locks A-1001 then A-1002.  T2: transfer A-1002 -> A-1001 locks A-1002 then A-1001.")
        o.p("Lock-ordering is OFF; each lock step is slowed by 0.4 s so both transactions hold their first lock (the classic interleaving).")
        m = mark(c)
        o.h("5a) Wait-for-graph detection switched OFF, lock timeout 1.0 s, no retries -> the deadlock is real")
        c.config(flags={"ordered": False, "max_retries": 0}, node_cfg={"step_delay": 0.4, "detect": False, "lock_timeout": 1.0})
        t0 = time.time()
        r = run_pair(c, *pair)
        dt = time.time() - t0
        for i, x in enumerate(r, 1):
            o.p("    T%d result: %s %s" % (i, x["status"], x.get("error", "")))
        o.logs(c, "A1", "LOCK TIMEOUT", m)
        o.check(any(x.get("error") == "lock timeout" for x in r) and dt >= 1.0, "neither transaction could proceed until the lock timeout fired (>= 1.0 s): a genuine deadlock")
        o.check(c.node_rpc("A1", {"op": "STATUS"})["deadlocks"] == 0, "no detection ran (as configured)")

        o.h("5b) Wait-for-graph detection ON (timeout stays as safety net), victim is retried automatically")
        c.config(flags={"ordered": False, "max_retries": 6}, node_cfg={"step_delay": 0.4, "detect": True, "lock_timeout": 1.5})
        m = mark(c)
        before = c.node_rpc("A1", {"op": "STATUS"})["deadlocks"]
        before_bal = bals(c, ["A-1001", "A-1002"])
        t0 = time.time()
        r = run_pair(c, *pair)
        dt = time.time() - t0
        for i, x in enumerate(r, 1):
            o.p("    T%d result: %s after %d attempt(s)" % (i, x["status"], x["attempts"]))
        o.h("Branch A log (wait-for graph and victim selection)")
        o.logs(c, "A1", "DEADLOCK|deadlock victim", m)
        o.h("Coordinator log (abort + retry of the victim)")
        o.logs(c, "coordinator", "retry|voted NO", m)
        st = c.node_rpc("A1", {"op": "STATUS"})
        o.p("    deadlocks detected by A1: %d, resolved in %.1f s (not a timeout)" % (st["deadlocks"] - before, dt))
        o.check(st["deadlocks"] - before >= 1, "wait-for-graph cycle detected")
        o.check(all(x["status"] == "COMMITTED" for x in r) and sorted(x["attempts"] for x in r) == [1, 2], "victim aborted and retried; both transfers finally committed")
        o.check(bals(c, ["A-1001", "A-1002"]) == before_bal, "opposite equal transfers cancel out: balances back to start")
        o.check(total(c) == SYSTEM_TOTAL, "total money unchanged")

        o.h("5c) Cross-branch deadlock (A-1001 -> B-2001 against B-2001 -> A-1001): cycle spans two nodes, broken by lock timeout")
        m = mark(c)
        c.config(flags={"ordered": False, "max_retries": 10}, node_cfg={"step_delay": 0.4, "detect": True, "lock_timeout": 1.0})
        r = run_pair(c, ("A-1001", "B-2001"), ("B-2001", "A-1001"))
        for i, x in enumerate(r, 1):
            o.p("    T%d result: %s after %d attempt(s)" % (i, x["status"], x["attempts"]))
        o.logs(c, "A1", "LOCK TIMEOUT", m)
        o.logs(c, "B1", "LOCK TIMEOUT", m)
        o.check(all(x["status"] == "COMMITTED" for x in r), "both transfers committed after the timeout victim was retried")
        o.check(total(c) == SYSTEM_TOTAL, "total money unchanged")
    o.save()


def s06():
    o = Out("06_deadlock_prevented.txt", "SCENARIO 6 - Same opposite transfers WITH ordered locking: deadlock prevented")
    with Cluster() as c:
        o.p("Ordered locking ON: every transaction takes account locks in sorted account-id order (and the coordinator contacts branches in sorted order).")
        c.config(flags={"ordered": True}, node_cfg={"step_delay": 0.4, "detect": True})
        o.h("Run the same two opposite transfers as scenario 5")
        t0 = time.time()
        r = run_pair(c, ("A-1001", "A-1002"), ("A-1002", "A-1001"))
        for i, x in enumerate(r, 1):
            o.p("    T%d result: %s after %d attempt(s)" % (i, x["status"], x["attempts"]))
        o.logs(c, "A1", "PREPARE")
        st = c.node_rpc("A1", {"op": "STATUS"})
        o.p("    deadlocks detected: %d, lock timeouts: %d" % (st["deadlocks"], st["lock_timeouts"]))
        o.h("Cross-branch version (A-1001 <-> B-2001)")
        r2 = run_pair(c, ("A-1001", "B-2001"), ("B-2001", "A-1001"))
        for i, x in enumerate(r2, 1):
            o.p("    T%d result: %s after %d attempt(s)" % (i, x["status"], x["attempts"]))
        sb = c.node_rpc("B1", {"op": "STATUS"})
        o.check(all(x["status"] == "COMMITTED" and x["attempts"] == 1 for x in r + r2), "all four transfers committed at the first attempt (no abort, no retry)")
        o.check(st["deadlocks"] == 0 and st["lock_timeouts"] == 0 and sb["lock_timeouts"] == 0, "no deadlock and no timeout happened: circular wait was made impossible")
        o.check(total(c) == SYSTEM_TOTAL, "total money unchanged")
    o.save()


def s07():
    o = Out("07_concurrent_transfers.txt", "SCENARIO 7 - 65 concurrent random transfers from 8 client connections: total money invariant")
    with Cluster() as c:
        c.config(flags={"ordered": True})
        rnd = random.Random(2026)
        jobs = []
        while len(jobs) < 60:
            s, d = rnd.choice(ALL_ACCOUNTS), rnd.choice(ALL_ACCOUNTS)
            if s != d:
                jobs.append((s, d, rnd.randint(100, 20000)))          # D 1.00 .. D 200.00
        jobs += [(rnd.choice(ALL_ACCOUNTS), "A-1001", 9_999_900) for _ in range(5)]  # these must fail
        jobs = [j for j in jobs if j[0] != j[1]]
        rnd.shuffle(jobs)
        before, tb = {n: c.db_balances(n) for n in PRIMARIES}, total(c)
        o.p("    requests: %d (8 parallel sessions), accounts: %d, total money before = %s" % (len(jobs), len(ALL_ACCOUNTS), fmt(tb)))
        res = []
        mu = threading.Lock()

        def worker(chunk):
            cl = c.client("teller1")
            for s, d, a in chunk:
                r = cl.request("TRANSFER", src=s, dst=d, amount=a)
                with mu:
                    res.append(r)
            cl.close()
        t0 = time.time()
        ts = [threading.Thread(target=worker, args=(jobs[i::8],)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        dt = time.time() - t0
        committed = sum(r["status"] == "COMMITTED" for r in res)
        aborted = [r for r in res if r["status"] == "ABORTED"]
        o.p("    finished in %.1f s -> committed: %d, aborted: %d (reasons: %s)" % (dt, committed, len(aborted), sorted({r["error"].split(" in ")[0] for r in aborted})))
        o.h("Money check")
        ta, tr = total(c), total(c, STANDBYS)
        allb = {a: v for n in PRIMARIES for a, v in c.db_balances(n).items()}
        for br, n in zip("ABC", PRIMARIES):
            o.p("    branch %s total: %s" % (br, fmt(sum(c.db_balances(n).values()))))
        o.p("    total after (primaries) = %s   total after (standbys) = %s" % (fmt(ta), fmt(tr)))
        o.p("    lowest single balance = %s" % fmt(min(allb.values())))
        st = c.admin().request("ADMIN_VIEW")
        o.p("    coordinator stats:", st["stats"])
        o.check(len(res) == len(jobs), "all %d requests answered" % len(jobs))
        o.check(ta == tb == SYSTEM_TOTAL, "TOTAL MONEY INVARIANT HOLDS: %s before = %s after" % (fmt(tb), fmt(ta)))
        o.check(tr == SYSTEM_TOTAL, "standby replicas hold the same total")
        o.check(min(allb.values()) >= 0, "no account is negative")
        o.check(len(aborted) == 5 and all("insufficient" in r["error"] for r in aborted), "exactly the 5 oversized transfers were aborted (insufficient funds)")
        o.check(all(not c.node_rpc(n, {"op": "STATUS"})["in_doubt"] and not c.node_rpc(n, {"op": "STATUS"})["locks"] for n in PRIMARIES), "no in-doubt transactions and no leftover locks")
    o.save()


def s08():
    o = Out("08_auth_and_access_control.txt", "SCENARIO 8 - Authentication (PBKDF2), wrong password, role-based access control, audit log")
    import sqlite3
    with Cluster() as c:
        o.h("Password storage (coordinator DB, table users) - no plaintext, per-user salt")
        for r in sqlite3.connect(os.path.join(c.dir, "coordinator.db")).execute("SELECT username, role, iterations, salt, pw_hash FROM users"):
            o.p("    %-8s %-9s PBKDF2-HMAC-SHA256 x%d  salt=%s...  hash=%s..." % (r[0], r[1], r[2], r[3][:12], r[4][:16]))
        o.h("Login attempts")
        cl = c.client(None)
        r1 = cl.login("alice", "wrong-password")
        o.p("    alice / wrong password  ->", r1)
        r2 = cl.login("mallory", "anything")
        o.p("    unknown user            ->", r2)
        r3 = cl.request("BALANCE", acct="A-1001")
        o.p("    request before login    ->", r3)
        o.h("Role checks")
        alice = c.client("alice")
        o.p("    alice (customer) logged in, accounts:", alice.accounts)
        tests = [
            ("alice reads her own A-1001", alice.request("BALANCE", acct="A-1001")),
            ("alice reads bob's A-1002", alice.request("BALANCE", acct="A-1002")),
            ("alice deposits cash", alice.request("DEPOSIT", acct="A-1001", amount=100)),
            ("alice transfers from bob's account", alice.request("TRANSFER", src="A-1002", dst="A-1001", amount=100)),
            ("alice opens admin view", alice.request("ADMIN_VIEW")),
            ("alice transfers from her own account", alice.request("TRANSFER", src="A-1001", dst="A-1002", amount=100)),
        ]
        teller = c.client("teller1")
        tests += [("teller deposits cash to A-1002", teller.request("DEPOSIT", acct="A-1002", amount=100)),
                  ("teller opens admin view", teller.request("ADMIN_VIEW"))]
        admin = c.client("admin")
        tests += [("admin opens admin view", {"ok": admin.request("ADMIN_VIEW")["ok"]}),
                  ("admin tries to move money", admin.request("TRANSFER", src="A-1001", dst="A-1002", amount=1))]
        for name, r in tests:
            o.p("    %-38s -> %s" % (name, r.get("error") or r.get("status") or ("OK balance=%s" % fmt(r["balance"]) if "balance" in r else "OK")))
        o.h("Audit log (as returned by the admin view)")
        for row in admin.request("ADMIN_VIEW", n=40)["audit"]:
            o.p("    #%-3d %-8s %-9s %-10s %-9s %s" % (row[0], row[2], row[3], row[4], row[6][:30], row[5][:50]))
        o.check(r1["ok"] is False and r2["ok"] is False and r1["error"] == r2["error"], "wrong password and unknown user rejected with the same message")
        o.check(r3["error"] == "login required", "no operation possible before login")
        denied = [n for n, r in tests if "denied" in str(r.get("error"))]
        o.check(len(denied) == 6, "6 forbidden actions were denied: " + "; ".join(denied))
        o.check(all(r.get("ok") for n, r in tests if n in ("alice reads her own A-1001", "alice transfers from her own account", "teller deposits cash to A-1002", "admin opens admin view")), "permitted actions succeeded")
    o.save()


def s09():
    o = Out("09_encryption_tamper_replay.txt", "SCENARIO 9 - AES-256-GCM on the wire: captured ciphertext, tampering rejected, replay rejected")
    with Cluster() as c:
        port = c.cfg["coordinator"]["client_port"]
        proxy = MitmProxy(port)
        cl = BankClient(proxy.port, c.cfg["server_pub"]).connect()
        o.h("An eavesdropping proxy sits between client and server and records every byte")
        cl.login("alice", "Alice#2026")
        cl.request("TRANSFER", src="A-1001", dst="A-1002", amount=100)
        cl.request("BALANCE", acct="A-1001")
        cl.request("BALANCE", acct="A-1001")
        o.p("    plaintext of frame 1 : {\"op\":\"LOGIN\",\"user\":\"alice\",\"password\":\"Alice#2026\"}")
        o.p("    on the wire, frame 1 : %s..." % proxy.c2s[1][:40].hex())
        o.p("    plaintext of frame 2 : {\"op\":\"TRANSFER\",\"src\":\"A-1001\",\"dst\":\"A-1002\",\"amount\":100}")
        o.p("    on the wire, frame 2 : %s..." % proxy.c2s[2][:40].hex())
        o.p("    server reply, frame 1: %s..." % proxy.s2c[1][:40].hex())
        o.p("    frame layout: 8-byte sequence number | AES-256-GCM ciphertext | 16-byte tag   (frame 1 is %d bytes)" % len(proxy.c2s[1]))
        o.p("    client hello (frame 0) carries only the ephemeral X25519 public key: %s..." % proxy.c2s[0][:24].hex())
        wire = b"".join(proxy.c2s + proxy.s2c)
        words = [b"alice", b"Alice#2026", b"password", b"TRANSFER", b"A-1001", b"BALANCE", b"amount"]
        found = [w.decode() for w in words if w in wire]
        o.p("    captured %d frames, %d bytes; searching for %s -> found: %s" % (len(proxy.c2s) + len(proxy.s2c), len(wire), [w.decode() for w in words], found or "nothing"))
        same_pt = (proxy.c2s[3][8:], proxy.c2s[4][8:])
        o.p("    the identical request 'BALANCE A-1001' sent twice produced different ciphertext:", same_pt[0] != same_pt[1])
        o.check(not found, "no plaintext word (user name, password, account, operation) appears in the captured traffic")
        o.check(same_pt[0] != same_pt[1], "identical messages encrypt differently (unique nonce per message)")

        o.h("Tampering: the proxy flips ONE bit of the TRANSFER frame in flight")
        p2 = MitmProxy(port, tamper_index=2)
        c2 = BankClient(p2.port, c.cfg["server_pub"]).connect()
        c2.login("alice", "Alice#2026")
        before = c.db_balances("A1")["A-1001"]
        try:
            c2.request("TRANSFER", src="A-1001", dst="A-1002", amount=100)
            dropped = False
        except Exception as e:
            dropped = True
            o.p("    client side: request failed (%s)" % type(e).__name__)
        time.sleep(0.3)
        o.logs(c, "coordinator", "SECURITY TAMPER")
        o.check(dropped and c.db_balances("A1")["A-1001"] == before, "modified message rejected by the GCM tag check, no money moved")

        o.h("Replay: the proxy delivers a copy of a captured, valid TRANSFER frame a second time")
        p3 = MitmProxy(port, replay_index=2)
        c3 = BankClient(p3.port, c.cfg["server_pub"]).connect()
        c3.login("alice", "Alice#2026")
        before = c.db_balances("A1")["A-1001"]
        r = c3.request("TRANSFER", src="A-1001", dst="A-1002", amount=5000)
        time.sleep(0.5)
        o.p("    transfer reply:", r["status"])
        o.logs(c, "coordinator", "SECURITY REPLAY")
        o.p("    A-1001 balance change: %s (one transfer of D 50.00 expected, not two)" % fmt(c.db_balances("A1")["A-1001"] - before))
        o.check(c.db_balances("A1")["A-1001"] == before - 5000, "replayed frame rejected (sequence number already used): transfer executed exactly once")
        o.h("Audit trail of the security events")
        for row in c.client("admin").request("ADMIN_VIEW", n=40)["audit"]:
            if row[4] == "SECURITY":
                o.p("    #%d %s %s: %s -> %s" % (row[0], row[2], row[4], row[5], row[6]))
        o.check(total(c) == SYSTEM_TOTAL, "total money unchanged")
    o.save()


def s10():
    o = Out("10_stale_vs_strong_read.txt", "SCENARIO 10 - Strong read (primary) vs eventually consistent read (lagging standby)")
    with Cluster() as c:
        t = c.client("teller1")
        o.p("Replication to the standby of Branch A is slowed by 2.0 s (injected lag). Account A-1003 starts at D 10,000.00.")
        c.config(nodes=["A1"], node_cfg={"repl_delay": 2.0})
        o.h("t = 0.0 s: teller deposits D 500.00 to A-1003")
        r = t.request("DEPOSIT", acct="A-1003", amount=50000)
        o.p("    deposit:", r["status"])
        strong = t.request("BALANCE", acct="A-1003", consistency="strong")
        stale = t.request("BALANCE", acct="A-1003", consistency="eventual")
        o.p("    strong read   from %s (primary): %s  [WAL position %d]" % (strong["node"], fmt(strong["balance"]), strong["wal_id"]))
        o.p("    eventual read from %s (standby): %s  [WAL position %d]   <-- STALE" % (stale["node"], fmt(stale["balance"]), stale["wal_id"]))
        time.sleep(2.6)
        o.h("t = 2.6 s: replication has arrived")
        late = t.request("BALANCE", acct="A-1003", consistency="eventual")
        o.p("    eventual read from %s (standby): %s  [WAL position %d]" % (late["node"], fmt(late["balance"]), late["wal_id"]))
        o.check(strong["balance"] == 1_050_000, "strong read returns the committed value immediately")
        o.check(stale["balance"] == 1_000_000 and stale["wal_id"] < strong["wal_id"], "standby read was briefly stale (older WAL position)")
        o.check(late["balance"] == 1_050_000, "standby converged to the primary value (eventual consistency)")
        o.p("    Note: all writes still go through 2PC on the primary; only READS from the standby are eventually consistent.")
    o.save()


def s11():
    o = Out("11_cli_session.txt", "SCENARIO 11 - Menu-driven CLI client (scripted keystrokes)")
    with Cluster() as c:
        def session(lines):
            it = iter(lines)
            buf = io.StringIO()

            def inp(prompt=""):
                v = next(it)
                shown = "*" * len(v) if prompt.startswith("Password") else v
                buf.write("%s%s\n" % (prompt, shown))
                return v
            with contextlib.redirect_stdout(buf):
                cl = c.client(None)
                cli(cl, inp=inp)
                cl.close()
            return buf.getvalue().rstrip("\n")
        o.h("Session 1: customer alice (one wrong password first)")
        o.p(session(["alice", "oops", "alice", "Alice#2026", "1", "A-1001", "s", "4", "A-1001", "C-3001", "75.50", "1", "C-3001", "e",
                     "5", "A-1001", "2", "A-1001", "10", "6", "7"]))
        o.h("Session 2: admin")
        o.p(session(["admin", "Admin#2026", "6", "7"]))
        o.check(c.db_balances("A1")["A-1001"] == 1_000_000 - 7550, "CLI transfer of D 75.50 was applied")
    o.save()


ALL = {1: s01, 2: s02, 3: s03, 4: s04, 5: s05, 6: s06, 7: s07, 8: s08, 9: s09, 10: s10, 11: s11}

if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    chosen = [int(a) for a in sys.argv[1:]] or sorted(ALL)
    for n in chosen:
        ALL[n]()
        print()
    print("DEMO SUMMARY: %d checks, %d passed, %d failed" % (len(RESULTS), sum(RESULTS), len(RESULTS) - sum(RESULTS)))
    sys.exit(0 if all(RESULTS) else 1)
