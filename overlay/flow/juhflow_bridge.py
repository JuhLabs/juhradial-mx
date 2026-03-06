"""JuhFlow Bridge - Linux side of the JuhFlow cross-platform connection.

Handles the encrypted TCP link between Linux (JuhRadial MX) and
Mac/Windows (JuhFlow companion app). Uses our own simple protocol
rather than Marconi, since JuhFlow runs alongside Logi Options+
and proxies Flow events.

Protocol: length-prefixed JSON over AES-256-GCM encrypted TCP.
Discovery: UDP broadcast beacons on port 59872 (separate from Logi's 59870).

Message types:
  - handshake:    X25519 public key exchange (plaintext, first message only)
  - edge_hit:     cursor hit a screen edge -> peer should show cursor
  - cursor_warp:  warp cursor to specific position
  - clipboard:    clipboard content sync
  - device_switch: switch MX device channel via HID++
  - heartbeat:    keepalive
  - config:       flow configuration sync
  - peer_status:  connected peers list
"""

import json
import logging
import os
import socket
import struct
import threading
import time
from typing import Callable, Dict, Optional

from .crypto import (
    build_encrypted_packet,
    decrypt_payload,
    derive_aes_key,
    derive_shared_secret,
    generate_x25519_keypair,
    parse_encrypted_packet,
)
from .keys import generate_identity

logger = logging.getLogger("juhradial.flow.bridge")

# JuhFlow bridge port (distinct from Logi ports)
JUHFLOW_TCP_PORT = 59872
JUHFLOW_DISCOVERY_PORT = 59873
JUHFLOW_BEACON_INTERVAL = 3.0

# Message types
MSG_HANDSHAKE = "handshake"
MSG_EDGE_HIT = "edge_hit"
MSG_CURSOR_WARP = "cursor_warp"
MSG_CLIPBOARD = "clipboard"
MSG_DEVICE_SWITCH = "device_switch"
MSG_HEARTBEAT = "heartbeat"
MSG_CONFIG = "config"
MSG_PEER_STATUS = "peer_status"

# Framing
FRAME_HEADER_LEN = 4  # ui32 BE length prefix


def _send_framed(sock, data):
    """Send length-prefixed message."""
    sock.sendall(struct.pack('>I', len(data)) + data)


def _recv_framed(sock):
    """Receive length-prefixed message. Returns None on disconnect."""
    header = b""
    while len(header) < FRAME_HEADER_LEN:
        chunk = sock.recv(FRAME_HEADER_LEN - len(header))
        if not chunk:
            return None
        header += chunk

    msg_len = struct.unpack('>I', header)[0]
    if msg_len > 1024 * 1024:  # 1MB max
        return None

    data = b""
    while len(data) < msg_len:
        chunk = sock.recv(min(msg_len - len(data), 65536))
        if not chunk:
            return None
        data += chunk
    return data


class JuhFlowBridge:
    """Linux-side bridge for JuhFlow companion app connections.

    Acts as both server (accepts connections from JuhFlow Mac/Win app)
    and discovery broadcaster (lets JuhFlow apps find us on LAN).
    """

    def __init__(self, on_edge_hit=None, on_clipboard=None,
                 on_device_switch=None, on_config=None,
                 tcp_port=None, discovery_port=None):
        # Callbacks
        self.on_edge_hit = on_edge_hit
        self.on_clipboard = on_clipboard
        self.on_device_switch = on_device_switch
        self.on_config = on_config

        # Ports (overridable for testing)
        self._tcp_port = tcp_port or JUHFLOW_TCP_PORT
        self._discovery_port = discovery_port or JUHFLOW_DISCOVERY_PORT

        # Identity
        self._private_key, self._public_key_bytes, self._node_id = generate_identity()

        # State
        self.running = False
        self._server_sock = None
        self._server_thread = None
        self._discovery_thread = None
        self._heartbeat_thread = None

        # Connected peers: {peer_id: PeerConnection}
        self._peers = {}
        self._peers_lock = threading.Lock()

        # Get local IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self._local_ip = s.getsockname()[0]
            s.close()
        except OSError:
            self._local_ip = "127.0.0.1"

    def start(self):
        """Start the bridge server and discovery broadcaster."""
        if self.running:
            return
        self.running = True

        # Start TCP server
        try:
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.bind(("", self._tcp_port))
            self._server_sock.listen(5)
            self._server_sock.settimeout(1.0)
            self._server_thread = threading.Thread(
                target=self._accept_loop, daemon=True
            )
            self._server_thread.start()
            logger.info("JuhFlow bridge server on TCP %d", self._tcp_port)
        except OSError as e:
            logger.error("Cannot start bridge server: %s", e)

        # Start discovery broadcaster
        self._discovery_thread = threading.Thread(
            target=self._discovery_loop, daemon=True
        )
        self._discovery_thread.start()

        # Start heartbeat
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()

    def stop(self):
        """Stop the bridge."""
        self.running = False
        with self._peers_lock:
            for peer in self._peers.values():
                peer.close()
            self._peers.clear()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass

    def send_edge_hit(self, edge, position, screen, ctrl_key=False,
                      relative_position=None):
        """Send an edge hit event to all connected JuhFlow peers."""
        msg = {
            "type": MSG_EDGE_HIT,
            "edge": edge,
            "position": {"x": position[0], "y": position[1]},
            "screen": screen,
            "ctrl_key": ctrl_key,
            "timestamp": time.time(),
        }
        if relative_position is not None:
            msg["relative_position"] = relative_position
        self._broadcast(msg)

    def send_clipboard(self, content, content_type="text/plain"):
        """Send clipboard content to peers."""
        msg = {
            "type": MSG_CLIPBOARD,
            "content": content,
            "content_type": content_type,
            "timestamp": time.time(),
        }
        self._broadcast(msg)

    def send_device_switch(self, device_id, channel):
        """Request device channel switch on peer."""
        msg = {
            "type": MSG_DEVICE_SWITCH,
            "device_id": device_id,
            "channel": channel,
            "timestamp": time.time(),
        }
        self._broadcast(msg)

    def get_peers(self):
        """Return list of connected peers."""
        with self._peers_lock:
            return [
                {
                    "id": pid,
                    "hostname": p.hostname,
                    "platform": p.platform,
                    "ip": p.ip,
                    "connected_at": p.connected_at,
                }
                for pid, p in self._peers.items()
            ]

    def _broadcast(self, msg):
        """Send message to all connected peers."""
        with self._peers_lock:
            peers = list(self._peers.values())
        for peer in peers:
            peer.send(msg)

    def _accept_loop(self):
        """Accept incoming TCP connections."""
        while self.running:
            try:
                conn, addr = self._server_sock.accept()
                logger.info("Bridge connection from %s:%d", addr[0], addr[1])
                handler = threading.Thread(
                    target=self._handle_connection,
                    args=(conn, addr),
                    daemon=True,
                )
                handler.start()
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    logger.error("Accept error")

    def _handle_connection(self, conn, addr):
        """Handle incoming connection with X25519 handshake."""
        peer = None
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.settimeout(10.0)

            # Step 1: Receive peer's handshake (plaintext JSON with pubkey)
            data = _recv_framed(conn)
            if not data:
                conn.close()
                return

            handshake = json.loads(data.decode('utf-8'))
            if handshake.get("type") != MSG_HANDSHAKE:
                logger.warning("Expected handshake, got: %s", handshake.get("type"))
                conn.close()
                return

            peer_pubkey = bytes.fromhex(handshake["public_key"])
            peer_hostname = handshake.get("hostname", addr[0])
            peer_platform = handshake.get("platform", "unknown")

            # Step 2: Send our handshake back
            our_handshake = {
                "type": MSG_HANDSHAKE,
                "public_key": self._public_key_bytes.hex(),
                "hostname": socket.gethostname(),
                "platform": "linux",
                "node_id": self._node_id.hex(),
                "software": "JuhRadialMX",
            }
            _send_framed(conn, json.dumps(our_handshake).encode('utf-8'))

            # Step 3: Derive shared AES key
            shared_secret = derive_shared_secret(self._private_key, peer_pubkey)
            aes_key = derive_aes_key(shared_secret)

            # Step 4: Create peer connection
            peer_id = handshake.get("node_id", addr[0])
            peer = PeerConnection(
                conn=conn,
                peer_id=peer_id,
                hostname=peer_hostname,
                platform=peer_platform,
                ip=addr[0],
                aes_key=aes_key,
                node_id=self._node_id,
                on_message=self._on_peer_message,
            )

            with self._peers_lock:
                old = self._peers.get(peer_id)
                if old:
                    old.close()
                self._peers[peer_id] = peer

            logger.info("JuhFlow peer connected: %s (%s, %s)",
                        peer_hostname, peer_platform, addr[0])

            # Message loop (encrypted from here on)
            conn.settimeout(30.0)
            peer.run()

        except Exception as e:
            logger.debug("Connection handler error: %s", e)
        finally:
            if peer:
                with self._peers_lock:
                    self._peers.pop(peer.peer_id, None)
                peer.close()
            else:
                conn.close()
            logger.info("Bridge connection from %s closed", addr[0])

    def _on_peer_message(self, peer_id, msg):
        """Dispatch received messages to callbacks."""
        msg_type = msg.get("type", "")

        if msg_type == MSG_EDGE_HIT and self.on_edge_hit:
            self.on_edge_hit(peer_id, msg)
        elif msg_type == MSG_CLIPBOARD and self.on_clipboard:
            self.on_clipboard(peer_id, msg)
        elif msg_type == MSG_DEVICE_SWITCH and self.on_device_switch:
            self.on_device_switch(peer_id, msg)
        elif msg_type == MSG_CONFIG and self.on_config:
            self.on_config(peer_id, msg)

    def _discovery_loop(self):
        """Broadcast UDP discovery beacons."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError as e:
            logger.error("Discovery socket failed: %s", e)
            return

        beacon = json.dumps({
            "type": "juhflow_discovery",
            "hostname": socket.gethostname(),
            "ip": self._local_ip,
            "port": self._tcp_port,
            "platform": "linux",
            "software": "JuhRadialMX",
            "public_key": self._public_key_bytes.hex(),
        }).encode('utf-8')

        count = 0
        while self.running:
            try:
                sock.sendto(beacon, ("255.255.255.255", self._discovery_port))
                count += 1
                if count == 1 or count % 20 == 0:
                    logger.debug("Bridge beacon #%d sent", count)
            except OSError:
                pass

            for _ in range(int(JUHFLOW_BEACON_INTERVAL * 10)):
                if not self.running:
                    break
                time.sleep(0.1)

        sock.close()

    def _heartbeat_loop(self):
        """Send periodic heartbeats to all peers."""
        while self.running:
            msg = {"type": MSG_HEARTBEAT, "ts": time.time()}
            self._broadcast(msg)
            for _ in range(50):  # 5 seconds
                if not self.running:
                    return
                time.sleep(0.1)


class PeerConnection:
    """Encrypted connection to a JuhFlow peer."""

    def __init__(self, conn, peer_id, hostname, platform, ip,
                 aes_key, node_id, on_message=None):
        self.conn = conn
        self.peer_id = peer_id
        self.hostname = hostname
        self.platform = platform
        self.ip = ip
        self.aes_key = aes_key
        self.node_id = node_id
        self.on_message = on_message
        self.connected_at = time.time()
        self._closed = False

    def send(self, msg):
        """Encrypt and send a message."""
        if self._closed:
            return False
        try:
            payload = json.dumps(msg).encode('utf-8')
            packet = build_encrypted_packet(self.node_id, self.aes_key, payload)
            _send_framed(self.conn, packet)
            return True
        except Exception:
            return False

    def run(self):
        """Receive loop - blocks until disconnect."""
        while not self._closed:
            try:
                data = _recv_framed(self.conn)
                if data is None:
                    break

                parsed = parse_encrypted_packet(data)
                if not parsed:
                    continue

                _, nonce, tag, ciphertext = parsed
                plaintext = decrypt_payload(self.aes_key, nonce, tag, ciphertext)
                msg = json.loads(plaintext.decode('utf-8'))

                if msg.get("type") == MSG_HEARTBEAT:
                    continue

                if self.on_message:
                    self.on_message(self.peer_id, msg)

            except Exception as e:
                if not self._closed:
                    logger.debug("Peer %s recv error: %s", self.hostname, e)
                break

    def close(self):
        """Close the connection."""
        self._closed = True
        try:
            self.conn.close()
        except OSError:
            pass
