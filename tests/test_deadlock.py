"""Requirement 3 (system level): real deadlock without ordering, prevention with ordering."""
import threading, time
from src.seed import SYSTEM_TOTAL

def run_pair(cluster, a, b, amt=1000, pairs=None):
    pairs = pairs or [(a, b), (b, a)]
    res = [None, None]
    def w(i, s, d):
        c = cluster.client("teller1"); res[i] = c.request("TRANSFER", src=s, dst=d, amount=amt); c.close()
    ts = [threading.Thread(target=w, args=(i, s, d)) for i, (s, d) in enumerate(pairs)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return res

def test_deadlock_without_ordering_is_detected_and_victim_retried(cluster):
    cluster.config(flags={"ordered": False, "max_retries": 6}, node_cfg={"step_delay": 0.3, "detect": True})
    r = run_pair(cluster, "A-1001", "A-1002")
    assert all(x["status"] == "COMMITTED" for x in r)
    assert sorted(x["attempts"] for x in r) == [1, 2]          # one victim was retried
    st = cluster.node_rpc("A1", {"op": "STATUS"})
    assert st["deadlocks"] >= 1
    assert cluster.total_from_db(["A1", "B1", "C1"]) == SYSTEM_TOTAL

def test_deadlock_blocks_both_when_detection_is_off(cluster):
    cluster.config(flags={"ordered": False, "max_retries": 0}, node_cfg={"step_delay": 0.3, "detect": False, "lock_timeout": 1.0})
    t0 = time.time()
    r = run_pair(cluster, "A-1001", "A-1002")
    # real deadlock: neither can proceed until a lock timeout fires (the first timeout frees the other one)
    assert any(x["status"] == "ABORTED" and x["error"] == "lock timeout" for x in r)
    assert time.time() - t0 >= 1.0
    assert cluster.node_rpc("A1", {"op": "STATUS"})["deadlocks"] == 0
    assert cluster.total_from_db(["A1", "B1", "C1"]) == SYSTEM_TOTAL

def test_ordered_locking_prevents_deadlock(cluster):
    cluster.config(flags={"ordered": True}, node_cfg={"step_delay": 0.3})
    r = run_pair(cluster, "A-1001", "A-1002")
    assert all(x["status"] == "COMMITTED" and x["attempts"] == 1 for x in r)
    st = cluster.node_rpc("A1", {"op": "STATUS"})
    assert st["deadlocks"] == 0 and st["lock_timeouts"] == 0

def test_cross_branch_deadlock_broken_by_timeout_and_retry(cluster):
    cluster.config(flags={"ordered": False, "max_retries": 10}, node_cfg={"step_delay": 0.3, "lock_timeout": 1.0})
    r = run_pair(cluster, "A-1001", "B-2001")
    assert all(x["status"] == "COMMITTED" for x in r)
    assert cluster.total_from_db(["A1", "B1", "C1"]) == SYSTEM_TOTAL
