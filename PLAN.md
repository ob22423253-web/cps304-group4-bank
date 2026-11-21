# PLAN - CPS 304 Group 4: Fault-Tolerant Distributed Banking System

## Environment check
Python 3.12.3, pip 26 (PEP 668: installs use `--user --break-system-packages`), LibreOffice present,
Pillow 10.2, cryptography 41, pytest 8.3 present; python-docx and matplotlib installed now.
**Graphviz (`dot`) is NOT installed -> diagrams are drawn with matplotlib.**

## Folder layout
```
src/        crypto.py locks.py wal.py common.py branch.py coordinator.py client.py seed.py cluster.py netproxy.py
tests/      pytest suite (one file per requirement area)
demo/       run_demo.py, output/*.txt (one file per scenario)
docs/       report builder, diagrams/*.png, CPS304_Group4_Report.docx/.pdf
screenshots/ PNG renders of demo output, pytest summary, CLI session
```

## Design (summary)
* 7 OS processes: coordinator + 3 branches x (primary, hot standby). Each node has its own SQLite DB and TCP port.
* Accounts partitioned by prefix (A-xxxx on Branch A ...). Money stored as integer bututs (no floats).
* Coordinator runs 2PC (prepare / vote / commit-abort) with a durable decision log; participants keep a
  write-ahead log (table `wal`: PREPARE / COMMIT / ABORT) in SQLite; recovery re-locks in-doubt transactions and asks the coordinator.
* Primary ships WAL records to its standby (synchronous by default; an injected lag mode shows stale reads).
* Locks: per-account exclusive locks; wait-for graph cycle detection + lock timeout; ordered locking switch.
* Security: PBKDF2-HMAC-SHA256 passwords; roles customer/teller/admin; X25519 key exchange + HKDF ->
  AES-256-GCM per-direction keys, sequence-number nonces (replay protection); Ed25519 server pinning (clients) /
  HMAC pre-shared-key proof (inter-node); audit table.
* Fault injection: node failpoints (`os._exit`), real `kill()` of processes, MITM proxy for tamper/replay.

## Requirement -> evidence
| Requirement | Code | Demo scenario | Pytest | Report section |
|---|---|---|---|---|
| 1 Simulate multiple bank servers | branch.py, cluster.py, wal.py | 1, 4, 7 | test_cluster.py | 3, 4 |
| 2 Transaction consistency | coordinator.py (2PC), wal.py, branch.py | 1, 2, 3, 7, 10 | test_consistency.py | 5 |
| 3 Deadlock handling | locks.py, branch.py | 5, 6 | test_locks.py, test_deadlock.py | 6 |
| 4 Encryption | crypto.py, netproxy.py, coordinator.py (auth, audit) | 8, 9 | test_security.py | 7 |
| Fault tolerance | branch.py (recover/promote), coordinator.py (failover) | 3, 4 | test_fault_tolerance.py | 8 |
| Consistency models | branch.py replica reads | 10 | test_consistency.py | 5.5 |
| CLI client | client.py | 11 (CLI session) | test_cli.py | 9 |
