"""Security primitives: password hashing, key exchange, AES-256-GCM secure channel.

Handshake (per TCP connection):  X25519 ephemeral ECDH -> HKDF-SHA256 -> two 256-bit keys
(client->server and server->client).  The server proves its identity either with an
Ed25519 signature over the transcript (client links; client pins the public key) or with an
HMAC proof using a cluster pre-shared key (inter-node links, mutual).

Every message after the handshake is one AES-256-GCM frame:
    4-byte length | 8-byte sequence number | ciphertext+16-byte tag
The GCM nonce is 4 zero bytes + the sequence number, so a nonce is never reused with a key.
The receiver insists on sequence == last + 1, so a replayed frame is rejected.
"""
import hashlib
import hmac
import json
import os
import struct

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MAX_FRAME = 1 << 20


class SecurityError(Exception):
    pass


class TamperError(SecurityError):
    pass


class ReplayError(SecurityError):
    pass


class HandshakeError(SecurityError):
    pass


class ConnectionClosed(Exception):
    pass


# ---------------------------------------------------------------- passwords
def hash_password(password, salt=None, iterations=100_000):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return salt.hex(), digest.hex(), iterations


def verify_password(password, salt_hex, hash_hex, iterations):
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), iterations)
    return hmac.compare_digest(digest.hex(), hash_hex)


# ---------------------------------------------------------------- framing
def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionClosed("peer closed the connection")
        buf += chunk
    return buf


def send_frame(sock, data):
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_frame(sock):
    (n,) = struct.unpack(">I", _recv_exact(sock, 4))
    if n > MAX_FRAME:
        raise TamperError("frame too large")
    return _recv_exact(sock, n)


# ---------------------------------------------------------------- secure channel
class SecureConn:
    def __init__(self, sock, send_key, recv_key):
        self.sock = sock
        self._tx = AESGCM(send_key)
        self._rx = AESGCM(recv_key)
        self.send_seq = 0
        self.recv_seq = 0

    @staticmethod
    def _nonce(seq):
        return b"\x00\x00\x00\x00" + struct.pack(">Q", seq)

    def send(self, obj):
        data = json.dumps(obj, separators=(",", ":")).encode()
        self.send_seq += 1
        ct = self._tx.encrypt(self._nonce(self.send_seq), data, None)
        send_frame(self.sock, struct.pack(">Q", self.send_seq) + ct)

    def recv(self):
        frame = recv_frame(self.sock)
        if len(frame) < 8 + 16:
            raise TamperError("frame too short")
        (seq,) = struct.unpack(">Q", frame[:8])
        try:
            data = self._rx.decrypt(self._nonce(seq), frame[8:], None)
        except InvalidTag:
            raise TamperError("GCM authentication tag mismatch (message modified)")
        if seq != self.recv_seq + 1:
            raise ReplayError("sequence %d received, expected %d (replay/reorder)" % (seq, self.recv_seq + 1))
        self.recv_seq = seq
        return json.loads(data)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def _raw(pub):
    return pub.public_bytes(Encoding.Raw, PublicFormat.Raw)


def _derive(shared, transcript):
    okm = HKDF(algorithm=hashes.SHA256(), length=64, salt=None, info=b"cps304-session" + transcript).derive(shared)
    return okm[:32], okm[32:]


def _psk_proof(psk, tag, transcript):
    return hmac.new(psk, tag + transcript, hashlib.sha256).digest()


def client_handshake(sock, server_pub=None, psk=None):
    """server_pub: Ed25519 public key bytes (pinned).  psk: cluster pre-shared key bytes."""
    eph = X25519PrivateKey.generate()
    cpub = _raw(eph.public_key())
    send_frame(sock, b"CPS1" + cpub)
    resp = recv_frame(sock)
    spub, proof = resp[:32], resp[32:]
    transcript = cpub + spub
    if server_pub is not None:
        try:
            Ed25519PublicKey.from_public_bytes(server_pub).verify(proof, transcript)
        except InvalidSignature:
            raise HandshakeError("server signature invalid - not the pinned server")
    elif psk is not None:
        if not hmac.compare_digest(proof, _psk_proof(psk, b"S", transcript)):
            raise HandshakeError("server PSK proof invalid")
        send_frame(sock, _psk_proof(psk, b"C", transcript))
    else:
        raise HandshakeError("no server authentication configured")
    k_c2s, k_s2c = _derive(eph.exchange(X25519PublicKey.from_public_bytes(spub)), transcript)
    return SecureConn(sock, k_c2s, k_s2c)


def server_handshake(sock, signer=None, psk=None):
    """signer: Ed25519PrivateKey (client-facing).  psk: cluster key bytes (internal)."""
    hello = recv_frame(sock)
    if hello[:4] != b"CPS1" or len(hello) != 36:
        raise HandshakeError("bad hello")
    cpub = hello[4:]
    eph = X25519PrivateKey.generate()
    spub = _raw(eph.public_key())
    transcript = cpub + spub
    if signer is not None:
        send_frame(sock, spub + signer.sign(transcript))
    elif psk is not None:
        send_frame(sock, spub + _psk_proof(psk, b"S", transcript))
        if not hmac.compare_digest(recv_frame(sock), _psk_proof(psk, b"C", transcript)):
            raise HandshakeError("client PSK proof invalid")
    else:
        raise HandshakeError("no authentication configured")
    k_c2s, k_s2c = _derive(eph.exchange(X25519PublicKey.from_public_bytes(cpub)), transcript)
    return SecureConn(sock, k_s2c, k_c2s)


def new_identity():
    priv = Ed25519PrivateKey.generate()
    return priv, _raw(priv.public_key())
