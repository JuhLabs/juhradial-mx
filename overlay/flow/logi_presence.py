"""Encrypted bidirectional TCP presence channel on port 59869

Handles both server (accept incoming) and client (connect outgoing)
for encrypted Flow presence. All messages use Logi-format encrypted
packets with length-prefix framing.
"""

import json
import logging
import socket
import struct
import threading
import time
from typing import Callable, Dict, Optional

from .constants import (
    LOGI_PRESENCE_PORT,
    MSG_HEARTBEAT,
)
from .crypto import (
    build_encrypted_packet,
    decrypt_payload,
    parse_encrypted_packet,
)

logger = logging.getLogger("juhradial.flow.presence")

# TCP message framing: [4 bytes BE u32 length][encrypted packet]
FRAME_HEADER_SIZE = 4
HEARTBEAT_INTERVAL = 5.0
RECV_TIMEOUT = 15.0


def _send_framed(sock, data: bytes):
    """Send a length-prefixed message."""
    frame = struct.pack(">I", len(data)) + data
    sock.sendall(frame)


def _recv_framed(sock) -> Optional[bytes]:
    """Receive a length-prefixed message. Returns None on disconnect."""
    header = b""
    while len(header) < FRAME_HEADER_SIZE:
        chunk = sock.recv(FRAME_HEADER_SIZE - len(header))
        if not chunk:
            return None
        header += chunk

    msg_len = struct.unpack(">I", header)[0]
    if msg_len > 65536:
        logger.warning("Message too large: %d bytes", msg_len)
        return None

    data = b""
    while len(data) < msg_len:
        chunk = sock.recv(msg_len - len(data))
        if not chunk:
            return None
        data += chunk
    return data


class FlowPresenceServer:
    """Encrypted TCP presence server.

    On connection: peer sends 32-byte node_id, server looks up AES key,
    sends own node_id back. Then encrypted message loop.
    """

    def __init__(self, node_id: bytes = None,
                 peer_aes_keys: Dict[str, bytes] = None,
                 on_message: Optional[Callable] = None):
        self.node_id = node_id or b"\x00" * 32
        self.running = False
        self.sock = None
        self.thread = None

        # {peer_name: aes_key_bytes}
        self.peer_aes_keys: Dict[str, bytes] = dict(peer_aes_keys or {})
        self._keys_lock = threading.Lock()

        # {peer_node_id_hex: (conn, peer_name, aes_key)}
        self.active_connections: Dict[str, tuple] = {}
        self._conn_lock = threading.Lock()

        # Callback for received messages: on_message(peer_name, message_dict)
        self.on_message = on_message

        # Reverse lookup: node_id_hex -> peer_name (populated during handshake)
        self._node_to_name: Dict[str, str] = {}

    def add_peer_key(self, peer_name: str, aes_key: bytes):
        with self._keys_lock:
            self.peer_aes_keys[peer_name] = aes_key

    def remove_peer_key(self, peer_name: str):
        with self._keys_lock:
            self.peer_aes_keys.pop(peer_name, None)

    def start(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("", LOGI_PRESENCE_PORT))
            self.sock.listen(5)
            self.sock.settimeout(1.0)

            self.running = True
            self.thread = threading.Thread(target=self._accept_loop, daemon=True)
            self.thread.start()
            print(f"[Flow] Encrypted presence server on TCP port {LOGI_PRESENCE_PORT}")
        except Exception as e:
            print(f"[Flow] Failed to start presence server: {e}")

    def stop(self):
        self.running = False
        with self._conn_lock:
            for nid_hex, (conn, _, _) in self.active_connections.items():
                try:
                    conn.close()
                except OSError:
                    pass
            self.active_connections.clear()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    def send_to_peer(self, peer_name: str, message: dict):
        """Send an encrypted message to a connected peer."""
        with self._conn_lock:
            for nid_hex, (conn, name, aes_key) in self.active_connections.items():
                if name == peer_name:
                    try:
                        payload = json.dumps(message).encode("utf-8")
                        packet = build_encrypted_packet(self.node_id, aes_key, payload)
                        _send_framed(conn, packet)
                        return True
                    except Exception as e:
                        logger.debug("Failed to send to %s: %s", peer_name, e)
                        return False
        return False

    def send_to_all(self, message: dict):
        """Send an encrypted message to all connected peers."""
        with self._conn_lock:
            connections = list(self.active_connections.items())

        for nid_hex, (conn, name, aes_key) in connections:
            try:
                payload = json.dumps(message).encode("utf-8")
                packet = build_encrypted_packet(self.node_id, aes_key, payload)
                _send_framed(conn, packet)
            except Exception as e:
                logger.debug("Failed to send to %s: %s", name, e)

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.sock.accept()
                logger.info("Presence connection from %s:%d", addr[0], addr[1])
                handler = threading.Thread(
                    target=self._handle_connection,
                    args=(conn, addr),
                    daemon=True,
                )
                handler.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error("Accept error: %s", e)

    def _handle_connection(self, conn: socket.socket, addr: tuple):
        """Handle incoming presence connection with node_id handshake."""
        peer_name = None
        aes_key = None
        nid_hex = None

        try:
            conn.settimeout(RECV_TIMEOUT)

            # Handshake: receive peer's 32-byte node_id
            peer_node_id = b""
            while len(peer_node_id) < 32:
                chunk = conn.recv(32 - len(peer_node_id))
                if not chunk:
                    return
                peer_node_id += chunk

            nid_hex = peer_node_id.hex()
            logger.info("Peer node_id: %s... from %s", nid_hex[:16], addr[0])

            # Send our node_id back
            conn.sendall(self.node_id)

            # Try to find matching AES key - try all peer keys
            with self._keys_lock:
                keys_snapshot = dict(self.peer_aes_keys)

            for name, key in keys_snapshot.items():
                # Accept the first key that matches any known peer
                # (we don't have node_id -> peer_name mapping yet,
                # so we accept the connection and figure out the peer from traffic)
                peer_name = name
                aes_key = key
                break

            if not aes_key:
                logger.warning("No matching AES key for peer %s from %s", nid_hex[:16], addr[0])
                conn.close()
                return

            # Register connection
            with self._conn_lock:
                self.active_connections[nid_hex] = (conn, peer_name, aes_key)
            self._node_to_name[nid_hex] = peer_name

            logger.info("Presence channel established with %s (%s)", peer_name, addr[0])

            # Message loop
            while self.running:
                data = _recv_framed(conn)
                if data is None:
                    break

                parsed = parse_encrypted_packet(data)
                if not parsed:
                    logger.debug("Non-packet data from %s", peer_name)
                    continue

                _, nonce, tag, ciphertext = parsed
                try:
                    plaintext = decrypt_payload(aes_key, nonce, tag, ciphertext)
                    message = json.loads(plaintext.decode("utf-8"))
                    logger.debug("Message from %s: type=%s", peer_name, message.get("type"))

                    if self.on_message:
                        self.on_message(peer_name, message)
                except Exception as e:
                    logger.debug("Decrypt/parse error from %s: %s", peer_name, e)

        except socket.timeout:
            logger.debug("Connection from %s timed out", addr[0])
        except Exception as e:
            if self.running:
                logger.debug("Connection error from %s: %s", addr[0], e)
        finally:
            if nid_hex:
                with self._conn_lock:
                    self.active_connections.pop(nid_hex, None)
                self._node_to_name.pop(nid_hex, None)
            conn.close()
            logger.info("Presence connection from %s closed", addr[0])


class FlowPresenceClient:
    """Encrypted TCP presence client - connects to a peer's presence server."""

    def __init__(self, peer_ip: str, peer_port: int = LOGI_PRESENCE_PORT,
                 our_node_id: bytes = None, peer_aes_key: bytes = None,
                 on_message: Optional[Callable] = None):
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self.our_node_id = our_node_id or b"\x00" * 32
        self.peer_aes_key = peer_aes_key
        self.on_message = on_message

        self.sock = None
        self.running = False
        self._thread = None
        self._heartbeat_thread = None
        self._connected = threading.Event()

    def start(self):
        """Start connection with reconnect loop."""
        self.running = True
        self._thread = threading.Thread(target=self._connect_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        self._connected.clear()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    def send_message(self, message: dict) -> bool:
        """Encrypt and send a message to the peer."""
        if not self._connected.is_set() or not self.sock:
            return False
        try:
            payload = json.dumps(message).encode("utf-8")
            packet = build_encrypted_packet(self.our_node_id, self.peer_aes_key, payload)
            _send_framed(self.sock, packet)
            return True
        except Exception as e:
            logger.debug("Send failed to %s: %s", self.peer_ip, e)
            self._connected.clear()
            return False

    def _connect_loop(self):
        """Reconnect loop with exponential backoff."""
        backoff = 1.0
        max_backoff = 30.0

        while self.running:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(5.0)
                self.sock.connect((self.peer_ip, self.peer_port))
                self.sock.settimeout(RECV_TIMEOUT)

                # Handshake: send our node_id, receive theirs
                self.sock.sendall(self.our_node_id)
                peer_node_id = b""
                while len(peer_node_id) < 32:
                    chunk = self.sock.recv(32 - len(peer_node_id))
                    if not chunk:
                        raise ConnectionError("Handshake failed")
                    peer_node_id += chunk

                logger.info("Connected to presence at %s:%d", self.peer_ip, self.peer_port)
                self._connected.set()
                backoff = 1.0

                # Start heartbeat
                self._heartbeat_thread = threading.Thread(
                    target=self._heartbeat_loop, daemon=True
                )
                self._heartbeat_thread.start()

                # Receive loop
                while self.running:
                    data = _recv_framed(self.sock)
                    if data is None:
                        break

                    parsed = parse_encrypted_packet(data)
                    if not parsed:
                        continue

                    _, nonce, tag, ciphertext = parsed
                    try:
                        plaintext = decrypt_payload(self.peer_aes_key, nonce, tag, ciphertext)
                        message = json.loads(plaintext.decode("utf-8"))
                        if self.on_message:
                            self.on_message(message)
                    except Exception as e:
                        logger.debug("Decrypt error from %s: %s", self.peer_ip, e)

            except Exception as e:
                if self.running:
                    logger.debug("Presence connection to %s failed: %s", self.peer_ip, e)
            finally:
                self._connected.clear()
                if self.sock:
                    try:
                        self.sock.close()
                    except OSError:
                        pass
                    self.sock = None

            if not self.running:
                break

            # Exponential backoff
            for _ in range(int(backoff * 10)):
                if not self.running:
                    return
                time.sleep(0.1)
            backoff = min(backoff * 2, max_backoff)

    def _heartbeat_loop(self):
        """Send heartbeats to keep connection alive."""
        while self.running and self._connected.is_set():
            self.send_message({"type": MSG_HEARTBEAT, "ts": time.time()})
            for _ in range(int(HEARTBEAT_INTERVAL * 10)):
                if not self.running or not self._connected.is_set():
                    return
                time.sleep(0.1)
