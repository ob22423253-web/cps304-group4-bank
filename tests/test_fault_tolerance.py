"""Fault tolerance: participant crash + WAL recovery, primary failure + failover, timeouts."""
import threading, time
from src.seed import SYSTEM_TOTAL
from src.wal import Store

TOTAL = lambda c: c.total_from_db(["A1", "B1", "C1"])

def wait_for(fn, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    return None

def test_participant_crash_after_prepare_aborts_then_recovers(cluster, teller):
    cluster.config(flags={"failover": False}, nodes=["B1"], node_cfg={"crash_at": "after_prepare_log"})
    r = teller.request("TRANSFER", src="A-1001", dst="B-2001", amount=10000)
    assert r["status"] == "ABORTED"
    assert cluster.wait_dead("B1")
    # B1 died holding a PREPARE record without outcome -> in doubt after restart
    assert [t for t, _ in Store(cluster.dir + "/B1.db").in_doubt()] == [r["txid"]]
    cluster.restart("B1")
    assert wait_for(lambda: cluster.node_rpc("B1", {"op": "STATUS"})["in_doubt"] == [])
    assert [r["kind"] for r in Store(cluster.dir + "/B1.db").records_after(0)] == ["PREPARE", "ABORT"]   # resolved as ABORT
    assert any("IN DOUBT" in l for l in cluster.log_lines("B1"))
    assert TOTAL(cluster) == SYSTEM_TOTAL and cluster.db_balances("B1")["B-2001"] == 1_000_000
    assert cluster.db_balances("A1")["A-1001"] == 1_000_000

def test_participant_crash_on_commit_recovers_to_commit(cluster, teller):
    cluster.config(flags={"failover": False}, nodes=["B1"], node_cfg={"crash_at": "before_commit"})
    r = teller.request("TRANSFER", src="A-1001", dst="B-2001", amount=10000)
    assert r["status"] == "COMMITTED_PENDING"           # decision is durable, B1 has not applied it yet
    assert cluster.db_balances("A1")["A-1001"] == 990_000 and cluster.db_balances("B1")["B-2001"] == 1_000_000
    cluster.restart("B1")
    assert wait_for(lambda: cluster.db_balances("B1")["B-2001"] == 1_010_000)
    assert TOTAL(cluster) == SYSTEM_TOTAL
    assert any("IN DOUBT" in l for l in cluster.log_lines("B1"))

def test_primary_killed_between_prepare_and_commit_fails_over(cluster, teller):
    cluster.config(flags={"commit_delay": 1.5})
    out = {}
    th = threading.Thread(target=lambda: out.update(teller.request("TRANSFER", src="A-1001", dst="B-2001", amount=30000)))
    th.start(); time.sleep(0.8)
    cluster.kill("B1")                                   # real SIGKILL while B1 is PREPARED
    th.join(20)
    assert out["status"] == "COMMITTED"
    v = cluster.admin().request("ADMIN_VIEW")
    assert v["active"]["B"] == "B2" and v["system_total"] == SYSTEM_TOTAL
    assert cluster.db_balances("B2")["B-2001"] == 1_030_000
    assert any("PROMOTED" in l for l in cluster.log_lines("B2"))
    # service continues on the new primary
    assert teller.request("DEPOSIT", acct="B-2002", amount=500)["status"] == "COMMITTED"

def test_failover_when_primary_already_down(cluster, teller):
    cluster.kill("A1")
    r = teller.request("TRANSFER", src="A-1001", dst="C-3001", amount=1000)
    assert r["status"] == "COMMITTED"
    assert cluster.admin().request("ADMIN_VIEW")["active"]["A"] == "A2"
    assert teller.request("BALANCE", acct="A-1001")["balance"] == 999_000

def test_rpc_timeout_aborts_transaction(cluster, teller):
    cluster.cfg["rpc_timeout"]
    cluster.config(flags={"failover": False}, nodes=["B1"], node_cfg={"hang_prepare": 6})
    t0 = time.time()
    r = teller.request("TRANSFER", src="A-1001", dst="B-2001", amount=1000)   # rpc timeout is 4s
    assert r["status"] == "ABORTED" and "timeout" in r["error"] and 3.5 < time.time() - t0 < 8
    assert cluster.db_balances("A1")["A-1001"] == 1_000_000 and TOTAL(cluster) == SYSTEM_TOTAL
