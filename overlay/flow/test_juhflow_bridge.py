"""Integration tests for JuhFlow bridge (Linux server <-> simulated Mac client).

Tests the full handshake, encrypted message round-trip, edge_hit dispatch,
clipboard sync, heartbeat keepalive, and reconnect after disconnect.
"""

import json
import os
import socket
import tempfile
import threading
import time
import unittest
import unittest.mock as mock
from typing import Any

from . import juhflow_bridge as bridge_module
from .crypto import (
    build_encrypted_packet,
    decrypt_payload,
    derive_aes_key,
    derive_shared_secret,
    generate_x25519_keypair,
    parse_encrypted_packet,
)
from .juhflow_bridge import (
    MSG_CLIPBOARD,
    MSG_EDGE_HIT,
    MSG_HANDSHAKE,
    MSG_HEARTBEAT,
    JuhFlowBridge,
    _recv_framed,
    _send_framed,
)


def _free_port():
    """Find a free TCP port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SimulatedMacClient:
    """Simulated JuhFlow Mac client for testing the bridge."""

    def __init__(self, server_port):
        self.server_port = server_port
        self._private_key, self._public_key_bytes = generate_x25519_keypair()
        self._node_id = os.urandom(32)
        self._aes_key = None
        self._sock = None

    def connect_and_handshake(self, timeout=5.0):
        """Connect to bridge server and complete X25519 handshake."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(timeout)
        self._sock.connect(("127.0.0.1", self.server_port))

        # Send our handshake (plaintext JSON with pubkey)
        handshake = {
            "type": MSG_HANDSHAKE,
            "public_key": self._public_key_bytes.hex(),
            "hostname": "test-mac",
            "platform": "macos",
            "node_id": self._node_id.hex(),
            "software": "JuhFlow",
        }
        _send_framed(self._sock, json.dumps(handshake).encode("utf-8"))

        # Receive server handshake
        data = _recv_framed(self._sock)
        if not data:
            raise ConnectionError("No handshake response from server")

        server_handshake = json.loads(data.decode("utf-8"))
        if server_handshake.get("type") != MSG_HANDSHAKE:
            raise ValueError("Expected handshake, got: " + server_handshake.get("type", ""))

        # Derive shared AES key
        peer_pubkey = bytes.fromhex(server_handshake["public_key"])
        shared_secret = derive_shared_secret(self._private_key, peer_pubkey)
        self._aes_key = derive_aes_key(shared_secret)

        return server_handshake

    def send_encrypted(self, msg):
        """Send an encrypted JSON message."""
        payload = json.dumps(msg).encode("utf-8")
        packet = build_encrypted_packet(self._node_id, self._aes_key, payload)
        _send_framed(self._sock, packet)

    def recv_encrypted(self, timeout=5.0):
        """Receive and decrypt a JSON message."""
        self._sock.settimeout(timeout)
        data = _recv_framed(self._sock)
        if data is None:
            return None

        parsed = parse_encrypted_packet(data)
        if not parsed:
            return None

        _, nonce, tag, ciphertext = parsed
        plaintext = decrypt_payload(self._aes_key, nonce, tag, ciphertext)
        return json.loads(plaintext.decode("utf-8"))

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass  # Socket already closed
            self._sock = None


def _make_bridge(**kwargs):
    """Create a bridge on a free port with discovery disabled."""
    tcp_port = _free_port()
    # Use a high random port for discovery to avoid permission issues
    disc_port = _free_port()
    bridge = JuhFlowBridge(
        tcp_port=tcp_port,
        discovery_port=disc_port,
        **kwargs,
    )
    return bridge, tcp_port


class TestJuhFlowBridgeHandshake(unittest.TestCase):
    """Test X25519 handshake between bridge server and simulated Mac client."""

    def setUp(self):
        self.bridge, self._port = _make_bridge()
        self.bridge.start()
        time.sleep(0.2)

    def tearDown(self):
        self.bridge.stop()
        time.sleep(0.1)

    def test_handshake_completes(self):
        """Handshake should exchange pubkeys and derive matching AES keys."""
        client = SimulatedMacClient(self._port)
        try:
            resp = client.connect_and_handshake()
            self.assertEqual(resp["type"], MSG_HANDSHAKE)
            self.assertEqual(resp["platform"], "linux")
            self.assertEqual(resp["software"], "JuhRadialMX")
            self.assertIn("public_key", resp)
            self.assertIn("node_id", resp)
            self.assertIsNotNone(client._aes_key)
            self.assertEqual(len(client._aes_key), 32)
        finally:
            client.close()

    def test_peer_registered_after_handshake(self):
        """Bridge should register the peer after successful handshake."""
        client = SimulatedMacClient(self._port)
        try:
            client.connect_and_handshake()
            time.sleep(0.2)
            peers = self.bridge.get_peers()
            self.assertEqual(len(peers), 1)
            self.assertEqual(peers[0]["hostname"], "test-mac")
            self.assertEqual(peers[0]["platform"], "macos")
        finally:
            client.close()


class TestJuhFlowBridgeMessaging(unittest.TestCase):
    """Test encrypted message exchange after handshake."""

    def setUp(self):
        self._received_edge_hits = []
        self._received_clipboards = []

        self.bridge, self._port = _make_bridge(
            on_edge_hit=lambda pid, msg: self._received_edge_hits.append((pid, msg)),
            on_clipboard=lambda pid, msg: self._received_clipboards.append((pid, msg)),
        )
        self.bridge.start()
        time.sleep(0.2)

        self.client = SimulatedMacClient(self._port)
        self.client.connect_and_handshake()
        time.sleep(0.2)

    def tearDown(self):
        self.client.close()
        self.bridge.stop()
        time.sleep(0.1)

    def test_encrypted_roundtrip(self):
        """Server should decrypt client messages correctly."""
        self.client.send_encrypted({
            "type": MSG_EDGE_HIT,
            "edge": "right",
            "position": {"x": 1920, "y": 540},
            "relative_position": 0.5,
            "screen": {"x": 0, "y": 0, "width": 1920, "height": 1080},
            "timestamp": time.time(),
        })
        time.sleep(0.3)
        self.assertEqual(len(self._received_edge_hits), 1)
        _, msg = self._received_edge_hits[0]
        self.assertEqual(msg["edge"], "right")
        self.assertAlmostEqual(msg["relative_position"], 0.5)

    def test_edge_hit_callback(self):
        """Edge hit from Mac client should trigger the on_edge_hit callback."""
        self.client.send_encrypted({
            "type": MSG_EDGE_HIT,
            "edge": "left",
            "position": {"x": 0, "y": 300},
            "relative_position": 0.28,
            "screen": {"x": 0, "y": 0, "width": 2560, "height": 1440},
        })
        time.sleep(0.3)
        self.assertEqual(len(self._received_edge_hits), 1)
        peer_id, msg = self._received_edge_hits[0]
        self.assertEqual(msg["type"], MSG_EDGE_HIT)
        self.assertEqual(msg["edge"], "left")
        self.assertAlmostEqual(msg["relative_position"], 0.28)

    def test_clipboard_sync(self):
        """Clipboard message from Mac should trigger on_clipboard callback."""
        self.client.send_encrypted({
            "type": MSG_CLIPBOARD,
            "content": "Hello from Mac!",
            "content_type": "text/plain",
        })
        time.sleep(0.3)
        self.assertEqual(len(self._received_clipboards), 1)
        _, msg = self._received_clipboards[0]
        self.assertEqual(msg["content"], "Hello from Mac!")

    def test_server_to_client_message(self):
        """Server should send encrypted messages to connected client."""
        self.bridge.send_edge_hit(
            "right", (1920, 540),
            {"x": 0, "y": 0, "width": 1920, "height": 1080},
        )
        msg = self.client.recv_encrypted(timeout=3.0)
        self.assertIsNotNone(msg)
        self.assertEqual(msg["type"], MSG_EDGE_HIT)
        self.assertEqual(msg["edge"], "right")

    def test_clipboard_from_server(self):
        """Server clipboard message should arrive at client."""
        self.bridge.send_clipboard("Pasted from Linux", "text/plain")
        msg = self.client.recv_encrypted(timeout=3.0)
        self.assertIsNotNone(msg)
        self.assertEqual(msg["type"], MSG_CLIPBOARD)
        self.assertEqual(msg["content"], "Pasted from Linux")

    def test_heartbeat_received(self):
        """Client should receive heartbeats from server within ~6 seconds."""
        msg = self.client.recv_encrypted(timeout=7.0)
        self.assertIsNotNone(msg)
        self.assertEqual(msg["type"], MSG_HEARTBEAT)

    def test_multiple_messages(self):
        """Multiple messages should all be delivered in order."""
        for i in range(5):
            self.client.send_encrypted({
                "type": MSG_EDGE_HIT,
                "edge": "right",
                "position": {"x": 1920, "y": i * 100},
                "relative_position": i / 5.0,
                "screen": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                "seq": i,
            })
        time.sleep(0.5)
        self.assertEqual(len(self._received_edge_hits), 5)
        for i, (_, msg) in enumerate(self._received_edge_hits):
            self.assertEqual(msg["seq"], i)


class TestJuhFlowBridgeReconnect(unittest.TestCase):
    """Test reconnect behavior after disconnect."""

    def setUp(self):
        self._received = []
        self.bridge, self._port = _make_bridge(
            on_edge_hit=lambda pid, msg: self._received.append(msg),
        )
        self.bridge.start()
        time.sleep(0.2)

    def tearDown(self):
        self.bridge.stop()
        time.sleep(0.1)

    def test_reconnect_new_session(self):
        """After disconnect, new client should connect with fresh handshake."""
        # First connection
        client1 = SimulatedMacClient(self._port)
        client1.connect_and_handshake()
        client1.send_encrypted({
            "type": MSG_EDGE_HIT, "edge": "right",
            "position": {"x": 0, "y": 0}, "relative_position": 0.5,
            "screen": {"x": 0, "y": 0, "width": 1920, "height": 1080},
        })
        time.sleep(0.3)
        self.assertEqual(len(self._received), 1)
        client1.close()
        time.sleep(0.5)

        # Second connection (fresh keys)
        client2 = SimulatedMacClient(self._port)
        client2.connect_and_handshake()
        client2.send_encrypted({
            "type": MSG_EDGE_HIT, "edge": "left",
            "position": {"x": 0, "y": 0}, "relative_position": 0.3,
            "screen": {"x": 0, "y": 0, "width": 2560, "height": 1440},
        })
        time.sleep(0.3)
        self.assertEqual(len(self._received), 2)
        self.assertEqual(self._received[1]["edge"], "left")
        client2.close()

    def test_peer_removed_after_disconnect(self):
        """Bridge should remove peer from list after disconnect."""
        client = SimulatedMacClient(self._port)
        client.connect_and_handshake()
        time.sleep(0.2)
        self.assertEqual(len(self.bridge.get_peers()), 1)

        client.close()
        time.sleep(1.0)
        self.assertEqual(len(self.bridge.get_peers()), 0)


class TestJuhFlowBridgeMultiPeer(unittest.TestCase):
    """Test multiple simultaneous peer connections."""

    def setUp(self):
        self.bridge, self._port = _make_bridge()
        self.bridge.start()
        time.sleep(0.2)

    def tearDown(self):
        self.bridge.stop()
        time.sleep(0.1)

    def test_two_clients(self):
        """Two clients should both connect and receive broadcasts."""
        client1 = SimulatedMacClient(self._port)
        client2 = SimulatedMacClient(self._port)
        try:
            client1.connect_and_handshake()
            client2.connect_and_handshake()
            time.sleep(0.3)
            self.assertEqual(len(self.bridge.get_peers()), 2)

            # Broadcast from server should reach both
            self.bridge.send_clipboard("shared text")
            msg1 = client1.recv_encrypted(timeout=3.0)
            msg2 = client2.recv_encrypted(timeout=3.0)
            self.assertIsNotNone(msg1)
            self.assertIsNotNone(msg2)
            self.assertEqual(msg1["content"], "shared text")
            self.assertEqual(msg2["content"], "shared text")
        finally:
            client1.close()
            client2.close()


class TestJuhFlowBridgeStatusPublication(unittest.TestCase):
    """Test status publication through the production heartbeat path."""

    def _run_heartbeat(self, bridge, status_path, presence_server=None):
        with mock.patch(
            f"{bridge_module.__package__}.get_presence_server",
            return_value=presence_server,
        ):
            bridge._heartbeat_once(status_path)

    @staticmethod
    def _bridge_with_peers(peers) -> Any:
        bridge = object.__new__(JuhFlowBridge)
        bridge.get_peers = mock.Mock(return_value=peers)
        bridge._broadcast = mock.Mock()
        return bridge

    def test_repeated_empty_heartbeats_do_not_replace_status_file(self):
        bridge = self._bridge_with_peers([])

        with tempfile.TemporaryDirectory() as home:
            status_path = os.path.join(home, "flow_status.json")
            real_replace = os.replace

            with (
                mock.patch("builtins.open") as status_open,
                mock.patch.object(
                    bridge_module.os, "replace", wraps=real_replace
                ) as replace,
            ):
                for _ in range(2):
                    self._run_heartbeat(bridge, status_path)

            status_open.assert_not_called()
            self.assertEqual(replace.call_count, 0)
            self.assertFalse(os.path.exists(status_path))

    def test_existing_status_is_removed_once_when_peers_are_empty(self):
        bridge = self._bridge_with_peers([])

        with tempfile.TemporaryDirectory() as home:
            status_path = os.path.join(home, "flow_status.json")
            with open(status_path, "w") as status_file:
                status_file.write("persisted")
            real_remove = os.remove

            with mock.patch.object(
                bridge_module.os, "remove", wraps=real_remove
            ) as remove:
                self._run_heartbeat(bridge, status_path)
                self._run_heartbeat(bridge, status_path)

            remove.assert_called_once_with(status_path)
            self.assertFalse(os.path.exists(status_path))

    def test_empty_status_tolerates_file_disappearing_before_removal(self):
        bridge = self._bridge_with_peers([])

        with (
            mock.patch.object(bridge_module.os.path, "exists", return_value=True),
            mock.patch.object(
                bridge_module.os, "remove", side_effect=FileNotFoundError
            ) as remove,
        ):
            self._run_heartbeat(bridge, "/tmp/flow_status.json")

        remove.assert_called_once_with("/tmp/flow_status.json")

    def test_connected_peer_is_written_atomically_with_expected_status(self):
        peer = {
            "id": "peer-1",
            "hostname": "test-mac",
            "platform": "macos",
            "ip": "192.0.2.10",
            "connected_at": 100.0,
        }
        bridge = self._bridge_with_peers([peer])

        with tempfile.TemporaryDirectory() as home:
            status_path = os.path.join(home, "flow_status.json")
            real_replace = os.replace

            with (
                mock.patch.object(bridge_module.time, "time", return_value=123.0),
                mock.patch.object(
                    bridge_module.os, "replace", wraps=real_replace
                ) as replace,
            ):
                self._run_heartbeat(bridge, status_path)

            replace.assert_called_once_with(status_path + ".tmp", status_path)
            with open(status_path) as status_file:
                status = json.load(status_file)
            self.assertEqual(status, {"peers": [peer], "updated_at": 123.0})
            bridge._broadcast.assert_called_once_with(
                {"type": MSG_HEARTBEAT, "ts": 123.0}
            )

    def test_disconnect_removes_previously_written_status(self):
        peer = {
            "id": "peer-1",
            "hostname": "test-mac",
            "platform": "macos",
            "ip": "192.0.2.10",
            "connected_at": 100.0,
        }
        bridge = self._bridge_with_peers([peer])

        with tempfile.TemporaryDirectory() as home:
            status_path = os.path.join(home, "flow_status.json")
            self._run_heartbeat(bridge, status_path)
            self.assertTrue(os.path.exists(status_path))

            bridge.get_peers.return_value = []
            self._run_heartbeat(bridge, status_path)

            self.assertFalse(os.path.exists(status_path))

    def test_presence_peer_is_counted_as_connected(self):
        bridge = self._bridge_with_peers([])
        presence_server = mock.Mock()
        presence_server._conn_lock = threading.Lock()
        presence_server.active_connections = {
            "0123456789abcdefcafebabe": (mock.Mock(), "office-mac", b"key")
        }

        with tempfile.TemporaryDirectory() as home:
            status_path = os.path.join(home, "flow_status.json")
            self._run_heartbeat(bridge, status_path, presence_server)

            with open(status_path) as status_file:
                status = json.load(status_file)
            self.assertEqual(
                status["peers"],
                [
                    {
                        "id": "0123456789abcdef",
                        "hostname": "office-mac",
                        "platform": "unknown",
                        "ip": "",
                        "connected_at": 0,
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
