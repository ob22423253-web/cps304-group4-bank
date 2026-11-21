"""Menu-driven CLI client."""
import io
from contextlib import redirect_stdout
from src.client import cli

def run_cli(cluster, lines):
    it = iter(lines)
    buf = io.StringIO()
    with redirect_stdout(buf):
        c = cluster.client(None)
        cli(c, inp=lambda prompt="": next(it))
        c.close()
    return buf.getvalue()

def test_cli_customer_session(cluster):
    out = run_cli(cluster, ["alice", "bad", "alice", "Alice#2026", "1", "A-1001", "s",
                            "4", "A-1001", "B-2001", "100", "5", "A-1001", "2", "A-1001", "5", "7"])
    assert "invalid username or password" in out and "Logged in as alice" in out
    assert "D 10,000.00" in out and "COMMITTED" in out and "D 9,900.00" in out
    assert "access denied" in out and "Goodbye" in out
    assert cluster.db_balances("A1")["A-1001"] == 990_000
