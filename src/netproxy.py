"""Man-in-the-middle TCP proxy used only by the demo/tests to capture, tamper with and replay frames."""
import socket
import struct
import threading

from .crypto import ConnectionClosed, recv_frame


class MitmProxy:
    """c2s frame index per connection: 0 = client hello, 1 = first encrypted message (LOGIN), 2 = next ..."""

    def __init__(self, target_port, tamper_index=None, replay_index=None, host="127.0.0.1"):
        self.host, self.target = host, target_port
        self.tamper_index, self.replay_index = tamper_index, replay_index
        self.c2s, self.s2c = [], []
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((host, 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    @staticmethod
    def _frame(body):
        return struct.pack(">I", len(body)) + body

    def _accept(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            try:
                s = socket.create_connection((self.host, self.target), timeout=5)
            except OSError:
                c.close()
                continue
            threading.Thread(target=self._pipe, args=(c, s, True), daemon=True).start()
            threading.Thread(target=self._pipe, args=(s, c, False), daemon=True).start()

    def _pipe(self, src, dst, upstream):
        i = 0
        try:
            while True:
                body = recv_frame(src)
                (self.c2s if upstream else self.s2c).append(body)
                if upstream and i == self.tamper_index:
                    body = body[:-1] + bytes([body[-1] ^ 0x01])          # flip one bit in the tag
                dst.sendall(self._frame(body))
                if upstream and i == self.replay_index:
                    dst.sendall(self._frame(body))                      # inject an identical copy
                i += 1
        except (ConnectionClosed, OSError):
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    s.close()
                except OSError:
                    pass

    def close(self):
        self.srv.close()
