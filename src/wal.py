"""SQLite storage for a branch node: accounts, write-ahead log (WAL), history.

The WAL table is an application-level 2PC log.  A PREPARE record (holding the intended
operations) is made durable before the node votes YES.  COMMIT applies the operations and
writes the COMMIT record in ONE SQLite transaction, so data and log can never disagree.
The same append() is used to replay records on the hot-standby (replication).
"""
import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(
    acct_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
    balance INTEGER NOT NULL CHECK(balance >= 0));
CREATE TABLE IF NOT EXISTS wal(
    id INTEGER PRIMARY KEY, txid TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('PREPARE','COMMIT','ABORT')),
    payload TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS wal_tx ON wal(txid);
CREATE TABLE IF NOT EXISTS history(
    id INTEGER PRIMARY KEY AUTOINCREMENT, txid TEXT, acct_id TEXT,
    delta INTEGER, balance_after INTEGER, ts REAL, memo TEXT);
"""


def connect(path):
    db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    return db


class Store:
    def __init__(self, path):
        self.mu = threading.RLock()
        self.db = connect(path)
        self.db.executescript(SCHEMA)

    def balance(self, acct):
        with self.mu:
            r = self.db.execute("SELECT balance FROM accounts WHERE acct_id=?", (acct,)).fetchone()
        return r[0] if r else None

    def total(self):
        with self.mu:
            return self.db.execute("SELECT COALESCE(SUM(balance),0) FROM accounts").fetchone()[0]

    def last_wal_id(self):
        with self.mu:
            return self.db.execute("SELECT COALESCE(MAX(id),0) FROM wal").fetchone()[0]

    def tx_state(self, txid):
        with self.mu:
            r = self.db.execute("SELECT kind FROM wal WHERE txid=? ORDER BY id DESC LIMIT 1", (txid,)).fetchone()
        return r[0] if r else None

    def prepared_ops(self, txid):
        with self.mu:
            r = self.db.execute("SELECT payload FROM wal WHERE txid=? AND kind='PREPARE'", (txid,)).fetchone()
        return json.loads(r[0])["ops"] if r else []

    def in_doubt(self):
        with self.mu:
            rows = self.db.execute(
                "SELECT w.txid, w.ts FROM wal w WHERE w.kind='PREPARE' AND NOT EXISTS "
                "(SELECT 1 FROM wal x WHERE x.txid=w.txid AND x.kind IN ('COMMIT','ABORT')) ORDER BY w.id").fetchall()
        return rows

    def records_after(self, wal_id, limit=500):
        with self.mu:
            rows = self.db.execute("SELECT id,txid,kind,payload,ts FROM wal WHERE id>? ORDER BY id LIMIT ?",
                                   (wal_id, limit)).fetchall()
        return [{"id": r[0], "txid": r[1], "kind": r[2], "payload": r[3], "ts": r[4]} for r in rows]

    def history(self, acct, n=10):
        with self.mu:
            rows = self.db.execute("SELECT txid,delta,balance_after,memo,id FROM history WHERE acct_id=? "
                                   "ORDER BY id DESC LIMIT ?", (acct, n)).fetchall()
        return [{"txid": r[0], "delta": r[1], "balance_after": r[2], "memo": r[3]} for r in rows]

    def append(self, txid, kind, payload=None, wal_id=None, ts=None):
        """Append a WAL record; COMMIT also applies the prepared operations atomically.
        Returns the wal id, or None if the record was redundant (idempotent)."""
        with self.mu:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                if kind in ("COMMIT", "ABORT"):
                    done = self.db.execute("SELECT kind FROM wal WHERE txid=? AND kind IN ('COMMIT','ABORT')",
                                           (txid,)).fetchone()
                    if done:
                        self.db.execute("ROLLBACK")
                        return None
                ts = ts or time.time()
                if wal_id is None:
                    wal_id = self.db.execute("INSERT INTO wal(txid,kind,payload,ts) VALUES(?,?,?,?)",
                                             (txid, kind, payload, ts)).lastrowid
                else:
                    self.db.execute("INSERT INTO wal(id,txid,kind,payload,ts) VALUES(?,?,?,?,?)",
                                    (wal_id, txid, kind, payload, ts))
                if kind == "COMMIT":
                    r = self.db.execute("SELECT payload FROM wal WHERE txid=? AND kind='PREPARE'", (txid,)).fetchone()
                    if r is None:
                        raise ValueError("COMMIT without PREPARE for %s" % txid)
                    for op in json.loads(r[0])["ops"]:
                        self.db.execute("UPDATE accounts SET balance=balance+? WHERE acct_id=?",
                                        (op["delta"], op["acct"]))
                        bal = self.db.execute("SELECT balance FROM accounts WHERE acct_id=?", (op["acct"],)).fetchone()[0]
                        self.db.execute("INSERT INTO history(txid,acct_id,delta,balance_after,ts,memo) VALUES(?,?,?,?,?,?)",
                                        (txid, op["acct"], op["delta"], bal, ts, op.get("memo", "")))
                self.db.execute("COMMIT")
                return wal_id
            except Exception:
                try:
                    self.db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
