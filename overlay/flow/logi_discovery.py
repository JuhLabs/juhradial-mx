"""Logi Options+ UDP broadcast discovery on port 59870

Handles both listening for Logi Options+ discovery broadcasts
and broadcasting our own presence. Supports encrypted beacons
for paired peers (Logi-format packets) and plaintext JSON for
unpaired JuhRadialMX discovery.
"""

import json
import logging
import socket
import threading
import time
from typing import Callable, Dict, Optional

from .constants import (
    LOGI_FLOW_PORT,
    LOGI_PRESENCE_PORT,
    LOGI_DISCOVERY_PORT,
    DISCOVERY_BROADCAST_INTERVAL,
)
from .crypto import build_encrypted_packet, decrypt_payload, parse_encrypted_packet

logger = logging.getLogger("juhradial.flow.discovery")


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
    1. Listens for discovery broadcasts and responds
    2. Sends encrypted beacons to paired peers (one per peer, each with peer's AES key)
    3. Broadcasts plaintext JuhRadialMX beacon for unpaired discovery
    4. Logs all packets in hex for protocol analysis
    """

    def __init__(self, hostname: str = None,
                 node_id: bytes = None,
                 private_key=None,
                 public_key_bytes: bytes = None,
                 on_unpaired_peer: Optional[Callable] = None):
        self.hostname = hostname or socket.gethostname()
        self.running = False
        self.listen_sock = None
        self.broadcast_sock = None
        self.listen_thread = None
        self.broadcast_thread = None
        self.discovered_peers: Dict[str, dict] = {}
        self._broadcast_count = 0

        # Crypto identity
        self.node_id = node_id
        self.private_key = private_key
        self.public_key_bytes = public_key_bytes

        # AES keys for paired peers: {peer_name: aes_key_bytes}
        self.peer_aes_keys: Dict[str, bytes] = {}
        self._peer_aes_lock = threading.Lock()

        # Callback for unpaired JuhRadialMX peers discovered
        self.on_unpaired_peer = on_unpaired_peer

        # Get local IP and broadcast address from OS
        self.local_ip = "127.0.0.1"
        self.broadcast_addr = "255.255.255.255"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self.local_ip = s.getsockname()[0]
            s.close()
            self.broadcast_addr = self._get_broadcast_addr()
        except OSError:
            pass

    def _get_broadcast_addr(self) -> str:
        """Get the real broadcast address for our network interface.

        Parses 'ip addr' output to find the broadcast address matching
        our local IP, handling any subnet mask (/22, /24, etc.).
        Falls back to 255.255.255.255 if detection fails.
        """
        import subprocess
        try:
            result = subprocess.run(
                ['ip', '-o', 'addr', 'show'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if self.local_ip in line and 'brd' in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'brd' and i + 1 < len(parts):
                            brd = parts[i + 1]
                            logger.info("Detected broadcast address: %s", brd)
                            return brd
        except Exception as e:
            logger.warning("Failed to detect broadcast addr: %s", e)

        ip_parts = self.local_ip.split('.')
        fallback = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.255"
        logger.info("Using fallback broadcast address: %s", fallback)
        return fallback

    def add_peer_key(self, peer_name: str, aes_key: bytes):
        """Add or update a peer's AES key for encrypted discovery."""
        with self._peer_aes_lock:
            self.peer_aes_keys[peer_name] = aes_key
        logger.info("Added peer key for encrypted discovery: %s", peer_name)

    def remove_peer_key(self, peer_name: str):
        """Remove a peer's AES key."""
        with self._peer_aes_lock:
            self.peer_aes_keys.pop(peer_name, None)

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
            self.listen_sock.bind(('0.0.0.0', LOGI_DISCOVERY_PORT))  # nosec B104 - LAN broadcast receiver, must bind all interfaces
            self.listen_sock.settimeout(1.0)

            self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listen_thread.start()
            logger.info("Logi discovery listener on UDP 0.0.0.0:%d", LOGI_DISCOVERY_PORT)
        except Exception as e:
            logger.error("Failed to start Logi discovery listener: %s", e)

    def _start_broadcaster(self):
        """Start the UDP broadcast sender"""
        try:
            self.broadcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            self.broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
            self.broadcast_thread.start()
            logger.info("Logi discovery broadcaster (interval: %ds)", DISCOVERY_BROADCAST_INTERVAL)
        except Exception as e:
            logger.error("Failed to start Logi discovery broadcaster: %s", e)

    def _listen_loop(self):
        """Main loop listening for discovery requests"""
        while self.running:
            try:
                data, addr = self.listen_sock.recvfrom(4096)
                if not data or addr[0] == self.local_ip:
                    continue

                # Try encrypted Logi-format packet first (>= 72 bytes, version match)
                if len(data) >= 72 and data[32:34] == b'\x00\x00':
                    parsed = parse_encrypted_packet(data)
                    if parsed:
                        node_id, nonce, tag, ciphertext = parsed
                        decrypted = self._try_decrypt_with_peer_keys(nonce, tag, ciphertext)
                        if decrypted:
                            peer_name, plaintext = decrypted
                            try:
                                msg = json.loads(plaintext.decode("utf-8"))
                                msg["_encrypted"] = True
                                msg["_peer_name"] = peer_name
                                self.discovered_peers[addr[0]] = {
                                    "last_seen": time.time(),
                                    "port": msg.get("port", LOGI_FLOW_PORT),
                                    "hostname": msg.get("hostname", addr[0]),
                                    "software": msg.get("software", "unknown"),
                                    "encrypted": True,
                                    "peer_name": peer_name,
                                }
                                logger.debug("Encrypted beacon from %s (%s)", peer_name, addr[0])
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                logger.debug("Decrypted non-JSON from %s", addr[0])
                            continue
                        # Could not decrypt - log for analysis
                        self._log_incoming_packet(data, addr)
                        continue

                # Try plaintext JSON
                try:
                    text = data.decode("utf-8")
                    msg = json.loads(text)
                    is_juhradial = msg.get("software") == "JuhRadialMX"

                    self.discovered_peers[addr[0]] = {
                        "last_seen": time.time(),
                        "port": msg.get("port", LOGI_FLOW_PORT),
                        "hostname": msg.get("hostname", addr[0]),
                        "software": msg.get("software", "unknown"),
                        "public_key": msg.get("public_key", ""),
                        "presence_port": msg.get("presence_port", LOGI_PRESENCE_PORT),
                        "encrypted": False,
                    }

                    if is_juhradial and self.on_unpaired_peer:
                        self.on_unpaired_peer(msg, addr[0])

                    self._send_response(addr)

                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Unknown format - log for protocol analysis
                    self._log_incoming_packet(data, addr)
                    self.discovered_peers[addr[0]] = {
                        "last_seen": time.time(),
                        "port": addr[1],
                        "data_preview": data[:100].hex(),
                    }
                    self._send_response(addr)

            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error("Listener error: %s", e)

    def _try_decrypt_with_peer_keys(self, nonce, tag, ciphertext):
        """Try decrypting with each known peer key. Returns (peer_name, plaintext) or None."""
        with self._peer_aes_lock:
            keys_snapshot = dict(self.peer_aes_keys)

        for peer_name, aes_key in keys_snapshot.items():
            try:
                plaintext = decrypt_payload(aes_key, nonce, tag, ciphertext)
                return peer_name, plaintext
            except Exception:
                continue
        return None

    def _broadcast_loop(self):
        """Periodically broadcast: encrypted beacons to paired peers, plaintext for unpaired."""
        while self.running:
            try:
                # Send encrypted beacon to each paired peer
                with self._peer_aes_lock:
                    keys_snapshot = dict(self.peer_aes_keys)

                if keys_snapshot and self.node_id:
                    announcement_json = json.dumps({
                        "hostname": self.hostname,
                        "ip": self.local_ip,
                        "port": LOGI_FLOW_PORT,
                        "presence_port": LOGI_PRESENCE_PORT,
                        "platform": "linux",
                        "software": "JuhRadialMX",
                        "flow_version": "1.0",
                    }).encode("utf-8")

                    for peer_name, aes_key in keys_snapshot.items():
                        try:
                            packet = build_encrypted_packet(
                                self.node_id, aes_key, announcement_json
                            )
                            self.broadcast_sock.sendto(
                                packet, (self.broadcast_addr, LOGI_DISCOVERY_PORT)
                            )
                        except Exception as e:
                            logger.debug("Encrypted broadcast to %s failed: %s", peer_name, e)

                # Always broadcast plaintext JuhRadialMX beacon for unpaired discovery
                plaintext_announcement = self._build_announcement()
                self.broadcast_sock.sendto(
                    plaintext_announcement,
                    (self.broadcast_addr, LOGI_DISCOVERY_PORT)
                )

                self._broadcast_count += 1
                if self._broadcast_count == 1 or self._broadcast_count % 12 == 0:
                    enc_count = len(keys_snapshot) if keys_snapshot else 0
                    logger.info(
                        "Broadcast #%d (%d encrypted + 1 plaintext) to %s:%d",
                        self._broadcast_count, enc_count,
                        self.broadcast_addr, LOGI_DISCOVERY_PORT,
                    )

            except Exception as e:
                if self.running:
                    logger.error("Broadcast error: %s", e)

            # Interruptible sleep
            for _ in range(int(DISCOVERY_BROADCAST_INTERVAL * 10)):
                if not self.running:
                    return
                time.sleep(0.1)

    def _build_announcement(self) -> bytes:
        """Build the plaintext discovery announcement packet (includes public key for pairing)."""
        announcement = {
            "hostname": self.hostname,
            "ip": self.local_ip,
            "port": LOGI_FLOW_PORT,
            "presence_port": LOGI_PRESENCE_PORT,
            "platform": "linux",
            "software": "JuhRadialMX",
            "flow_version": "1.0",
        }
        if self.public_key_bytes:
            announcement["public_key"] = self.public_key_bytes.hex()
        return json.dumps(announcement).encode("utf-8")

    def _send_response(self, addr):
        """Send a discovery response"""
        try:
            self.listen_sock.sendto(self._build_announcement(), addr)
            logger.debug("Sent response to %s", addr)
        except Exception as e:
            logger.debug("Failed to send response to %s: %s", addr, e)

    def _log_incoming_packet(self, data: bytes, addr: tuple):
        """Log packet details at DEBUG level for protocol analysis."""
        logger.debug("Unknown UDP packet from %s:%d (%d bytes): %s",
                      addr[0], addr[1], len(data), data[:64].hex())

    def get_discovered_peers(self) -> Dict[str, dict]:
        """Return discovered peers (prunes stale entries > 30s)"""
        now = time.time()
        self.discovered_peers = {
            ip: info for ip, info in self.discovered_peers.items()
            if now - info['last_seen'] < 30
        }
        return self.discovered_peers.copy()
