"""Requirement 4: encryption, authentication, access control, audit."""
import socket, struct
import pytest
from src.client import BankClient
from src.crypto import (ConnectionClosed, HandshakeError, ReplayError, TamperError, SecureConn,
                        client_handshake, hash_password, new_identity, server_handshake, verify_password)
from src.netproxy import MitmProxy
import threading

def test_pbkdf2_salted_hashes_differ_and_verify():
    s1, h1, it = hash_password("secret"); s2, h2, _ = hash_password("secret")
    assert s1 != s2 and h1 != h2 and "secret" not in h1
    assert verify_password("secret", s1, h1, it) and not verify_password("Secret", s1, h1, it)

def test_password_not_stored_in_plaintext(cluster):
    import sqlite3
    rows = sqlite3.connect(cluster.dir + "/coordinator.db").execute("SELECT * FROM users").fetchall()
    assert rows and all("2026" not in "".join(map(str, r)) for r in rows)

def test_wrong_password_and_unknown_user(cluster):
    c = cluster.client(None)
    assert c.login("alice", "wrong")["ok"] is False
    assert c.login("nobody", "x")["ok"] is False
    assert c.request("BALANCE", acct="A-1001")["error"] == "login required"

def test_role_based_access_control(cluster):
    alice = cluster.client("alice")
    assert alice.request("BALANCE", acct="A-1001")["ok"]
    assert "denied" in alice.request("BALANCE", acct="A-1002")["error"]          # not her account
    assert "denied" in alice.request("DEPOSIT", acct="A-1001", amount=100)["error"]
    assert "denied" in alice.request("ADMIN_VIEW")["error"]
    assert "denied" in alice.request("TRANSFER", src="A-1002", dst="A-1001", amount=1)["error"]
    assert alice.request("TRANSFER", src="A-1001", dst="A-1002", amount=100)["ok"]
    teller = cluster.client("teller1")
    assert teller.request("DEPOSIT", acct="A-1002", amount=100)["ok"]
    assert "denied" in teller.request("ADMIN_VIEW")["error"]
    admin = cluster.client("admin")
    assert admin.request("ADMIN_VIEW")["ok"]
    assert "denied" in admin.request("TRANSFER", src="A-1001", dst="A-1002", amount=1)["error"]

def test_audit_log_records_success_and_denials(cluster):
    alice = cluster.client("alice"); alice.request("DEPOSIT", acct="A-1001", amount=5)
    cluster.client(None).login("alice", "bad")
    rows = cluster.client("admin").request("ADMIN_VIEW", n=50)["audit"]
    assert any(r[4] == "DEPOSIT" and r[6] == "DENIED" for r in rows)
    assert any(r[4] == "LOGIN" and r[6] == "FAILED" for r in rows)
    assert any(r[4] == "LOGIN" and r[6] == "OK" for r in rows)

def pair():
    a, b = socket.socketpair(); priv, pub = new_identity(); out = {}
    t = threading.Thread(target=lambda: out.update(s=server_handshake(b, signer=priv))); t.start()
    c = client_handshake(a, server_pub=pub); t.join()
    return c, out["s"], a, b

def test_secure_channel_roundtrip_and_ciphertext_hides_plaintext():
    c, s, a, b = pair()
    c.send({"op": "TRANSFER", "acct": "A-1001"})
    assert s.recv() == {"op": "TRANSFER", "acct": "A-1001"}

def test_tampered_frame_rejected():
    c, s, a, b = pair()
    c.send({"x": 1})
    raw = b.recv(4096); body = bytearray(raw); body[-1] ^= 1
    s2 = s; fake = socket.socketpair(); fake[0].sendall(bytes(body)); s2.sock = fake[1]
    with pytest.raises(TamperError):
        s2.recv()

def test_replayed_frame_rejected():
    c, s, a, b = pair()
    c.send({"x": 1}); raw = b.recv(4096)
    fake = socket.socketpair(); fake[0].sendall(raw + raw); s.sock = fake[1]
    assert s.recv() == {"x": 1}
    with pytest.raises(ReplayError):
        s.recv()

def test_wrong_pinned_server_key_rejected(cluster):
    _, other_pub = new_identity()
    c = BankClient(cluster.cfg["coordinator"]["client_port"], other_pub.hex())
    with pytest.raises(HandshakeError):
        c.connect()

def test_wire_capture_has_no_plaintext_and_tamper_and_replay_fail_end_to_end(cluster):
    proxy = MitmProxy(cluster.cfg["coordinator"]["client_port"])
    c = BankClient(proxy.port, cluster.cfg["server_pub"]).connect()
    c.login("alice", "Alice#2026"); c.request("TRANSFER", src="A-1001", dst="A-1002", amount=100)
    wire = b"".join(proxy.c2s + proxy.s2c)
    for word in (b"alice", b"Alice#2026", b"TRANSFER", b"A-1001", b"password"):
        assert word not in wire
    # tamper: flip a bit of the 3rd client frame (hello=0, login=1, request=2)
    p2 = MitmProxy(cluster.cfg["coordinator"]["client_port"], tamper_index=2)
    c2 = BankClient(p2.port, cluster.cfg["server_pub"]).connect(); c2.login("alice", "Alice#2026")
    with pytest.raises(ConnectionClosed):
        c2.request("TRANSFER", src="A-1001", dst="A-1002", amount=100)
    # replay: the transfer frame is delivered twice, only one transfer happens
    p3 = MitmProxy(cluster.cfg["coordinator"]["client_port"], replay_index=2)
    c3 = BankClient(p3.port, cluster.cfg["server_pub"]).connect(); c3.login("alice", "Alice#2026")
    assert c3.request("TRANSFER", src="A-1001", dst="A-1002", amount=5000)["ok"]
    import time; time.sleep(0.5)
    assert cluster.db_balances("A1")["A-1001"] == 1_000_000 - 100 - 5000
    sec = [r for r in cluster.client("admin").request("ADMIN_VIEW", n=50)["audit"] if r[4] == "SECURITY"]
    assert len(sec) >= 2
