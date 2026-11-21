"""Requirement 2: transaction consistency (2PC / ACID) and consistency models."""
import random, threading, time
from src.seed import ALL_ACCOUNTS, SYSTEM_TOTAL

def test_cross_branch_transfer_commits_atomically(cluster, teller):
    r = teller.request("TRANSFER", src="A-1001", dst="B-2001", amount=25000)
    assert r["status"] == "COMMITTED"
    assert cluster.db_balances("A1")["A-1001"] == 975_000
    assert cluster.db_balances("B1")["B-2001"] == 1_025_000
    assert cluster.total_from_db(["A1", "B1", "C1"]) == SYSTEM_TOTAL

def test_insufficient_funds_aborts_and_changes_nothing(cluster, teller):
    before = [cluster.db_balances(n) for n in ("A1", "B1")]
    r = teller.request("TRANSFER", src="A-1001", dst="B-2001", amount=99_999_900)
    assert r["status"] == "ABORTED" and "insufficient" in r["error"]
    assert [cluster.db_balances(n) for n in ("A1", "B1")] == before
    assert cluster.node_rpc("A1", {"op": "STATUS"})["locks"] == {}

def test_abort_when_destination_vote_is_no(cluster, teller):
    # destination account is fine, source is on another branch; withdraw more than balance on dst side
    before = cluster.total_from_db(["A1", "B1", "C1"])
    r = teller.request("WITHDRAW", acct="C-3001", amount=2_000_000)
    assert r["status"] == "ABORTED"
    assert cluster.total_from_db(["A1", "B1", "C1"]) == before

def test_wal_records_written(cluster, teller):
    teller.request("TRANSFER", src="A-1002", dst="C-3002", amount=100)
    kinds = [r["kind"] for r in cluster.node_rpc("A1", {"op": "STATUS"}) and
             __import__("src.wal", fromlist=["Store"]).Store(cluster.dir + "/A1.db").records_after(0)]
    assert kinds == ["PREPARE", "COMMIT"]

def test_concurrent_transfers_preserve_total_money(cluster):
    cluster.config(flags={"ordered": True})
    rnd = random.Random(7)
    jobs = [(rnd.choice(ALL_ACCOUNTS), rnd.choice(ALL_ACCOUNTS), rnd.randint(100, 20000)) for _ in range(60)]
    jobs = [j for j in jobs if j[0] != j[1]]
    res = []
    def worker(chunk):
        c = cluster.client("teller1")
        for s, d, a in chunk:
            res.append(c.request("TRANSFER", src=s, dst=d, amount=a))
        c.close()
    ts = [threading.Thread(target=worker, args=(jobs[i::8],)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(res) == len(jobs) >= 50
    assert all(r["status"] == "COMMITTED" for r in res)
    assert cluster.total_from_db(["A1", "B1", "C1"]) == SYSTEM_TOTAL
    assert all(v >= 0 for n in ("A1", "B1", "C1") for v in cluster.db_balances(n).values())
    assert cluster.total_from_db(["A2", "B2", "C2"]) == SYSTEM_TOTAL      # replicas identical

def test_stale_replica_read_vs_strong_read(cluster, teller):
    cluster.config(nodes=["A1"], node_cfg={"repl_delay": 1.5})
    teller.request("DEPOSIT", acct="A-1003", amount=50000)
    strong = teller.request("BALANCE", acct="A-1003", consistency="strong")
    stale = teller.request("BALANCE", acct="A-1003", consistency="eventual")
    assert strong["balance"] == 1_050_000 and stale["balance"] == 1_000_000
    time.sleep(2.2)
    assert teller.request("BALANCE", acct="A-1003", consistency="eventual")["balance"] == 1_050_000
