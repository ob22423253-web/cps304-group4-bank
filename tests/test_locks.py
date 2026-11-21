"""Requirement 3 (unit level): lock manager, wait-for graph, timeout."""
import threading, time
import pytest
from src.locks import DeadlockVictim, LockManager, LockTimeout

def test_deadlock_detected_via_wait_for_graph():
    lm = LockManager()
    lm.acquire("T1", "x"); time.sleep(0.01); lm.acquire("T2", "y")
    out = {}
    def t1():
        try: lm.acquire("T1", "y", 2); out["T1"] = "ok"
        except DeadlockVictim: out["T1"] = "victim"
    th = threading.Thread(target=t1); th.start(); time.sleep(0.2)
    with pytest.raises(DeadlockVictim) as e:       # T2 is youngest -> victim, closes cycle T2->T1->T2
        lm.acquire("T2", "x", 2)
    assert set(e.value.cycle) == {"T1", "T2"} and lm.deadlocks == 1
    lm.release_all("T2"); th.join(2)
    assert out["T1"] == "ok"

def test_timeout_when_detection_off():
    lm = LockManager()
    lm.acquire("T1", "x"); lm.acquire("T2", "y")
    th = threading.Thread(target=lambda: pytest.raises(LockTimeout, lm.acquire, "T1", "y", 0.5, False)); th.start()
    time.sleep(0.1)
    t0 = time.time()
    with pytest.raises(LockTimeout):
        lm.acquire("T2", "x", 0.5, False)
    assert time.time() - t0 >= 0.45 and lm.deadlocks == 0
    th.join()

def test_lock_is_reentrant_and_released():
    lm = LockManager()
    lm.acquire("T1", "x"); lm.acquire("T1", "x")
    lm.release_all("T1")
    lm.acquire("T2", "x", 0.2)
