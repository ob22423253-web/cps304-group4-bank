"""Per-account exclusive lock manager with wait-for-graph deadlock detection and lock timeout."""
import threading
import time


class LockTimeout(Exception):
    pass


class DeadlockVictim(Exception):
    def __init__(self, cycle):
        super().__init__("deadlock victim, cycle=%s" % "->".join(cycle))
        self.cycle = cycle


class LockManager:
    def __init__(self, log=None):
        self.cv = threading.Condition()
        self.owner = {}      # account -> txid holding it
        self.waits = {}      # txid -> account it is waiting for (wait-for graph edges)
        self.started = {}    # txid -> time of first lock request (youngest = victim)
        self.victims = set()
        self.log = log or (lambda m: None)
        self.deadlocks = 0
        self.timeouts = 0

    def _cycle_from(self, start):
        path, cur = [start], start
        while True:
            acct = self.waits.get(cur)
            holder = self.owner.get(acct) if acct else None
            if holder is None:
                return None
            if holder == start:
                return path
            if holder in path:
                return None
            path.append(holder)
            cur = holder

    def acquire(self, txid, acct, timeout=2.0, detect=True):
        deadline = time.monotonic() + timeout
        with self.cv:
            self.started.setdefault(txid, time.monotonic())
            while True:
                holder = self.owner.get(acct)
                if holder is None or holder == txid:
                    self.owner[acct] = txid
                    self.waits.pop(txid, None)
                    return
                self.waits[txid] = acct
                if detect:
                    cycle = self._cycle_from(txid)
                    if cycle:
                        victim = max(cycle, key=lambda t: self.started.get(t, 0))
                        self.deadlocks += 1
                        desc = "; ".join("%s waits for %s held by %s" % (t, self.waits[t], self.owner[self.waits[t]])
                                         for t in cycle)
                        self.log("DEADLOCK detected (wait-for cycle %s -> %s): %s | victim = %s"
                                 % ("->".join(cycle), cycle[0], desc, victim))
                        if victim == txid:
                            self.waits.pop(txid, None)
                            raise DeadlockVictim(cycle)
                        self.victims.add(victim)
                        self.cv.notify_all()
                if txid in self.victims:
                    self.victims.discard(txid)
                    self.waits.pop(txid, None)
                    raise DeadlockVictim([txid])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.waits.pop(txid, None)
                    self.timeouts += 1
                    self.log("LOCK TIMEOUT: %s gave up waiting for %s held by %s" % (txid, acct, holder))
                    raise LockTimeout(acct)
                self.cv.wait(min(remaining, 0.05))

    def force(self, txid, accts):
        """Re-acquire locks for a recovered in-doubt transaction (no contention at startup)."""
        with self.cv:
            for a in accts:
                self.owner[a] = txid
            self.started.setdefault(txid, time.monotonic())

    def release_all(self, txid):
        with self.cv:
            for a in [a for a, t in self.owner.items() if t == txid]:
                del self.owner[a]
            self.waits.pop(txid, None)
            self.started.pop(txid, None)
            self.victims.discard(txid)
            self.cv.notify_all()

    def snapshot(self):
        with self.cv:
            return dict(self.owner)
