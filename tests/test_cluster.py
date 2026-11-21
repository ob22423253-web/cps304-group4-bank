"""Requirement 1: multiple bank servers (separate processes, own DBs, partitioned accounts, replication)."""
from src.cluster import NODES
from src.seed import SYSTEM_TOTAL

def test_seven_separate_processes(cluster):
    pids = {n: p.pid for n, p in cluster.procs.items()}
    assert len(pids) == 7 and len(set(pids.values())) == 7
    assert all(cluster.alive(n) for n in pids)

def test_each_node_has_own_db_and_partition(cluster):
    a, b = cluster.db_balances("A1"), cluster.db_balances("B1")
    assert set(a) == {"A-1001", "A-1002", "A-1003", "A-1004"}
    assert set(b) == {"B-2001", "B-2002", "B-2003", "B-2004"}
    assert not set(a) & set(b)

def test_node_status_roles(cluster):
    admin = cluster.admin()
    v = admin.request("ADMIN_VIEW")
    roles = {n: s["role"] for n, s in v["nodes"].items()}
    assert roles == {"A1": "primary", "A2": "backup", "B1": "primary", "B2": "backup", "C1": "primary", "C2": "backup"}
    assert v["system_total"] == SYSTEM_TOTAL

def test_replication_to_standby(cluster, teller):
    assert teller.request("DEPOSIT", acct="C-3001", amount=777)["ok"]
    assert cluster.db_balances("C2")["C-3001"] == cluster.db_balances("C1")["C-3001"] == 1_000_777
