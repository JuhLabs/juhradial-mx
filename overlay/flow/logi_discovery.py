"""Logi Options+ UDP broadcast discovery on port 59870

Handles both listening for Logi Options+ discovery broadcasts
and broadcasting our own presence. Includes hex dump logging
for protocol reverse-engineering.
"""

import json
import socket
import threading
import time
from typing import Dict

from flow.constants import (
    LOGI_FLOW_PORT,
    LOGI_PRESENCE_PORT,
    LOGI_DISCOVERY_PORT,
    DISCOVERY_BROADCAST_INTERVAL,
)


def _hex_dump(data: bytes, prefix: str = "") -> str:
    """Format bytes as hex dump for protocol analysis"""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f"{prefix}  {i:04x}: {hex_part:<48s}  {ascii_part}")
    return '\n'.join(lines)


class LogiFlowDiscoveryResponder:
    """UDP responder and broadcaster for Logi Options+ Flow discovery

    Logi Options+ uses UDP broadcast on port 59870 to discover Flow-compatible
    computers on the network. This class:
    1. Listens for discovery broadcasts from Logi Options+ and responds
    2. Periodically broadcasts our own presence so Logi Options+ can find us
    3. Logs all packets in hex for protocol reverse-engineering
    """

    def __init__(self, hostname: str = None):
        self.hostname = hostname or socket.gethostname()
        self.running = False
        self.listen_sock = None
        self.broadcast_sock = None
        self.listen_thread = None
        self.broadcast_thread = None
        self.discovered_peers: Dict[str, dict] = {}
        self._broadcast_count = 0

        # Get local IP and broadcast address
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self.local_ip = s.getsockname()[0]
            s.close()
        except OSError:
            self.local_ip = "127.0.0.1"

        # Derive broadcast address (assume /24 subnet)
        ip_parts = self.local_ip.split('.')
        self.broadcast_addr = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.255"

    def start(self):
        """Start listening for discovery requests and broadcasting our presence"""
        if self.running:
            return

        self.running = True
        self._start_listener()
        self._start_broadcaster()

    def stop(self):
        """Stop listening and broadcasting"""
        self.running = False
        for sock in (self.listen_sock, self.broadcast_sock):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass

    def _start_listener(self):
        """Start the UDP listener socket"""
        try:
            self.listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.listen_sock.bind(('0.0.0.0', LOGI_DISCOVERY_PORT))
            self.listen_sock.settimeout(1.0)

            self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listen_thread.start()
            print(f"[Flow] Logi discovery listener on UDP 0.0.0.0:{LOGI_DISCOVERY_PORT}")
        except Exception as e:
            print(f"[Flow] Failed to start Logi discovery listener: {e}")

    def _start_broadcaster(self):
        """Start the UDP broadcast sender"""
        try:
            self.broadcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            self.broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
            self.broadcast_thread.start()
            print(f"[Flow] Logi discovery broadcaster (interval: {DISCOVERY_BROADCAST_INTERVAL}s)")
        except Exception as e:
            print(f"[Flow] Failed to start Logi discovery broadcaster: {e}")

    def _listen_loop(self):
        """Main loop listening for discovery requests"""
        while self.running:
            try:
                data, addr = self.listen_sock.recvfrom(4096)
                if not data or addr[0] == self.local_ip:
                    continue

                self._log_incoming_packet(data, addr)
                self.discovered_peers[addr[0]] = {
                    'last_seen': time.time(),
                    'port': addr[1],
                    'data_preview': data[:100].hex()
                }
                self._send_response(addr)

            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[Flow Discovery] Listener error: {e}")

    def _broadcast_loop(self):
        """Periodically broadcast our presence on port 59870"""
        while self.running:
            try:
                announcement = self._build_announcement()
                self.broadcast_sock.sendto(
                    announcement,
                    (self.broadcast_addr, LOGI_DISCOVERY_PORT)
                )
                self._broadcast_count += 1
                if self._broadcast_count == 1 or self._broadcast_count % 12 == 0:
                    print(f"[Flow Discovery] Broadcast #{self._broadcast_count} to {self.broadcast_addr}:{LOGI_DISCOVERY_PORT}")
            except Exception as e:
                if self.running:
                    print(f"[Flow Discovery] Broadcast error: {e}")

            # Interruptible sleep
            for _ in range(int(DISCOVERY_BROADCAST_INTERVAL * 10)):
                if not self.running:
                    return
                time.sleep(0.1)

    def _build_announcement(self) -> bytes:
        """Build the discovery announcement packet"""
        return json.dumps({
            'hostname': self.hostname,
            'ip': self.local_ip,
            'port': LOGI_FLOW_PORT,
            'presence_port': LOGI_PRESENCE_PORT,
            'platform': 'linux',
            'software': 'JuhRadialMX',
            'flow_version': '1.0'
        }).encode('utf-8')

    def _send_response(self, addr):
        """Send a discovery response"""
        try:
            self.listen_sock.sendto(self._build_announcement(), addr)
            print(f"[Flow Discovery] Sent response to {addr}")
        except Exception as e:
            print(f"[Flow Discovery] Failed to send response: {e}")

    def _log_incoming_packet(self, data: bytes, addr: tuple):
        """Log full packet details for protocol analysis"""
        print(f"\n[Flow Discovery] === INCOMING UDP PACKET ===")
        print(f"[Flow Discovery] From: {addr[0]}:{addr[1]}")
        print(f"[Flow Discovery] Size: {len(data)} bytes")
        print(f"[Flow Discovery] Raw hex:")
        print(_hex_dump(data, "[Flow Discovery]"))

        try:
            text = data.decode('utf-8')
            print(f"[Flow Discovery] UTF-8: {text}")
            try:
                parsed = json.loads(text)
                print(f"[Flow Discovery] JSON: {json.dumps(parsed, indent=2)}")
            except json.JSONDecodeError:
                pass
        except UnicodeDecodeError:
            print(f"[Flow Discovery] (not valid UTF-8)")

        print(f"[Flow Discovery] === END PACKET ===\n")

    def get_discovered_peers(self) -> Dict[str, dict]:
        """Return discovered peers (prunes stale entries > 30s)"""
        now = time.time()
        self.discovered_peers = {
            ip: info for ip, info in self.discovered_peers.items()
            if now - info['last_seen'] < 30
        }
        return self.discovered_peers.copy()
