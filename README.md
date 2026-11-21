# Fault-Tolerant Distributed Banking System for the UTG Microfinance Unit

**CPS 304 Operating System II** - University of The Gambia - 1st semester 2026 - Practical coursework (30 marks) - Group 4
Submission date: 24 November 2026 - Lecturer: [LECTURER NAME] - Faculty/School: [FACULTY OR SCHOOL NAME]

| Matric number | Name | Role |
|---|---|---|
| 22223122 | [NAME 1] | Group Leader |
| 22516009 | [NAME 2] | Member |
| 22516018 | [NAME 3] | Member |
| 22423253 | [NAME 4] | Member |

Repository: https://github.com/ob22423253-web/cps304-group4-bank

Three branch servers (A, B, C), each a separate OS process with its own SQLite database and a hot-standby backup, coordinated by a
transaction coordinator that runs two-phase commit. Per-account locks with deadlock detection and prevention, AES-256-GCM encrypted and
authenticated messages, PBKDF2 passwords, roles, audit log, crash recovery and failover.
Python 3.10+ (tested on 3.12). Runs on Linux, WSL and Windows (no fork-only code).

## Install
```
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
`cryptography` and `pytest` are enough to run the system; `python-docx`, `matplotlib` and `Pillow` are only used to rebuild the report, diagrams and screenshots.
(On Debian/Ubuntu without a venv add `--user --break-system-packages`.)

## Run the demo
```
python demo/run_demo.py          # all 11 scenarios, labelled output, saved to demo/output/*.txt (about 2 minutes)
python demo/run_demo.py 5 6      # only some scenarios
```
Scenarios: 1 normal cross-branch transfer - 2 insufficient funds - 3 participant crash and WAL recovery - 4 primary killed, failover -
5 deadlock without ordering (detected, victim retried) - 6 deadlock prevented by ordered locking - 7 65 concurrent transfers, money invariant -
8 wrong password and forbidden roles - 9 encryption, tamper and replay - 10 stale replica read vs strong read - 11 CLI session.

## Run the tests
```
python -m pytest tests -v        # 33 tests, about 2.5 minutes
```

## Use the system by hand
```
python -m src.cluster up                          # terminal 1: starts the 7 processes (Ctrl-C stops them)
python -m src.client --config run/cluster.json    # terminal 2: menu-driven client
```

## Login accounts (demo credentials only, created by src/seed.py)
| User | Password | Role | Accounts |
|---|---|---|---|
| alice | Alice#2026 | customer | A-1001, B-2001, C-3001 |
| bob | Bob#2026 | customer | A-1002, B-2002, C-3002 |
| carol | Carol#2026 | customer | A-1003, B-2003, C-3003 |
| dave | Dave#2026 | customer | A-1004, B-2004, C-3004 |
| teller1 | Teller#2026 | teller | all |
| admin | Admin#2026 | admin | admin view and configuration only |

Every account opens with D 10,000.00 (system total D 120,000.00). Account ids start with the branch letter.

## Rebuild the report, diagrams, screenshots and code appendix
```
python docs/make_diagrams.py && python docs/make_screenshots.py && python docs/build_report.py && python docs/build_appendix.py
python docs/set_team.py "Name 1" "Name 2" "Name 3" "Name 4" "Lecturer name" "Faculty or school"   # writes real names, rebuilds the report
```
Needs LibreOffice (`soffice`) and poppler (`pdfinfo`, `pdftotext`).

## Project tree
```
src/
  crypto.py        X25519 + HKDF key exchange, AES-256-GCM secure channel, replay check, PBKDF2
  locks.py         per-account lock manager, wait-for graph, timeout
  wal.py           SQLite store: accounts, write-ahead log, history
  branch.py        branch server: 2PC participant, recovery, replication, promotion
  coordinator.py   gateway (login, roles, audit) + 2PC coordinator + failover
  client.py        client library and menu-driven CLI
  seed.py cluster.py common.py netproxy.py   seeding, process launcher, helpers, MITM proxy used by the demo
tests/             pytest: test_cluster, test_consistency, test_locks, test_deadlock, test_security, test_fault_tolerance, test_cli
demo/              run_demo.py and output/*.txt (real scenario output, pytest_summary.txt, run_all.txt)
docs/              CPS304_Group4_Report.docx/.pdf, CPS304_Group4_SourceCode_Appendix.docx/.pdf, team.json,
                   build_report.py build_appendix.py make_diagrams.py make_screenshots.py set_team.py, diagrams/*.png, figs/*.png
screenshots/       dark-terminal PNG renders of every scenario output, the pytest summary and the CLI session
PLAN.md  requirements.txt  README.md  .gitignore
```
Failures are injected with failpoints (`os._exit`), real process kills and a man-in-the-middle proxy; these admin-only hooks exist for the demo.

## Publish to GitHub (not done automatically)
```
git remote add origin https://github.com/ob22423253-web/cps304-group4-bank
git push -u origin main
```
