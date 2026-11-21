"""Create the initial (genesis) databases for all nodes and the coordinator."""
import os
import sqlite3

from .crypto import hash_password
from .wal import Store, connect

PBKDF2_ITERATIONS = 30_000           # demo value (fast tests); raise for production use
INITIAL_BALANCE = 1_000_000          # D 10,000.00 in bututs
ACCOUNTS = {                         # account -> owner (partitioned by branch prefix)
    "A": [("A-1001", "alice"), ("A-1002", "bob"), ("A-1003", "carol"), ("A-1004", "dave")],
    "B": [("B-2001", "alice"), ("B-2002", "bob"), ("B-2003", "carol"), ("B-2004", "dave")],
    "C": [("C-3001", "alice"), ("C-3002", "bob"), ("C-3003", "carol"), ("C-3004", "dave")],
}
USERS = {                            # demo credentials (documented in README)
    "alice": ("Alice#2026", "customer"),
    "bob": ("Bob#2026", "customer"),
    "carol": ("Carol#2026", "customer"),
    "dave": ("Dave#2026", "customer"),
    "teller1": ("Teller#2026", "teller"),
    "admin": ("Admin#2026", "admin"),
}
ALL_ACCOUNTS = [a for lst in ACCOUNTS.values() for a, _ in lst]
SYSTEM_TOTAL = INITIAL_BALANCE * len(ALL_ACCOUNTS)

COORD_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, salt TEXT, pw_hash TEXT, iterations INTEGER, role TEXT);
CREATE TABLE IF NOT EXISTS accounts(acct_id TEXT PRIMARY KEY, owner TEXT, branch TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, username TEXT, role TEXT,
                                 action TEXT, detail TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS decisions(txid TEXT PRIMARY KEY, decision TEXT, pending TEXT, ts REAL);
"""


def seed_all(data_dir, iterations=PBKDF2_ITERATIONS):
    os.makedirs(data_dir, exist_ok=True)
    for br, accts in ACCOUNTS.items():
        for node in (br + "1", br + "2"):
            path = os.path.join(data_dir, node + ".db")
            st = Store(path)
            st.db.execute("BEGIN")
            for a, owner in accts:
                st.db.execute("INSERT OR IGNORE INTO accounts VALUES(?,?,?)", (a, owner, INITIAL_BALANCE))
            st.db.execute("COMMIT")
            st.db.close()
    db = connect(os.path.join(data_dir, "coordinator.db"))
    db.executescript(COORD_SCHEMA)
    db.execute("BEGIN")
    for u, (pw, role) in USERS.items():
        salt, h, it = hash_password(pw, iterations=iterations)
        db.execute("INSERT OR REPLACE INTO users VALUES(?,?,?,?,?)", (u, salt, h, it, role))
    for br, accts in ACCOUNTS.items():
        for a, owner in accts:
            db.execute("INSERT OR REPLACE INTO accounts VALUES(?,?,?)", (a, owner, br))
    db.execute("COMMIT")
    db.close()
