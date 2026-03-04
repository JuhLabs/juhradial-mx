"""Logi Options+ TCP presence server on port 59869

Accepts presence connections and logs all data for protocol analysis.
"""

import socket
import threading

from flow.constants import LOGI_PRESENCE_PORT


class LogiFlowPresenceServer:
    """TCP presence server for Logi Options+ Flow

    Logi Options+ uses port 59869 for presence connections (ping/pong style).
    We accept connections and log everything for protocol analysis.
    """

    def __init__(self):
        self.hostname = socket.gethostname()
        self.running = False
        self.sock = None
        self.thread = None

    def start(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('', LOGI_PRESENCE_PORT))
            self.sock.listen(5)
            self.sock.settimeout(1.0)

            self.running = True
            self.thread = threading.Thread(target=self._accept_loop, daemon=True)
            self.thread.start()
            print(f"[Flow] Presence server on TCP port {LOGI_PRESENCE_PORT}")
        except Exception as e:
            print(f"[Flow] Failed to start presence server: {e}")

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.sock.accept()
                print(f"[Flow Presence] Connection from {addr[0]}:{addr[1]}")
                handler = threading.Thread(
                    target=self._handle_connection,
                    args=(conn, addr),
                    daemon=True
                )
                handler.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[Flow Presence] Accept error: {e}")

    def _handle_connection(self, conn: socket.socket, addr: tuple):
        """Handle a single presence connection with full logging"""
        try:
            conn.settimeout(30.0)
            while self.running:
                data = conn.recv(4096)
                if not data:
                    break

                print(f"\n[Flow Presence] === INCOMING TCP DATA ===")
                print(f"[Flow Presence] From: {addr[0]}:{addr[1]}")
                print(f"[Flow Presence] Size: {len(data)} bytes")
                for i in range(0, len(data), 16):
                    chunk = data[i:i+16]
                    hex_part = ' '.join(f'{b:02x}' for b in chunk)
                    ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                    print(f"[Flow Presence]   {i:04x}: {hex_part:<48s}  {ascii_part}")
                try:
                    print(f"[Flow Presence] UTF-8: {data.decode('utf-8')}")
                except UnicodeDecodeError:
                    pass
                print(f"[Flow Presence] === END DATA ===\n")

        except socket.timeout:
            print(f"[Flow Presence] Connection from {addr[0]} timed out")
        except Exception as e:
            if self.running:
                print(f"[Flow Presence] Connection error from {addr[0]}: {e}")
        finally:
            conn.close()
            print(f"[Flow Presence] Connection from {addr[0]} closed")
