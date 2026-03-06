#!/usr/bin/env python3
"""JuhFlow - macOS menubar companion app for JuhRadial MX Flow.

Monitors mouse position on Mac using Quartz event taps, detects screen
edge hits, and bridges to JuhRadial MX on Linux via encrypted TCP.

Architecture:
  1. Edge detection via Quartz CGEvent tap (mouse moves)
  2. Discovery via UDP broadcast beacons (find Linux peers)
  3. Encrypted TCP bridge to Linux JuhRadial MX
  4. Clipboard sync via NSPasteboard
  5. Cursor warp via CGWarpMouseCursorPosition

Requirements:
  pip3 install rumps cryptography pyobjc-framework-Quartz
"""

import json
import logging
import os
import socket
import struct
import subprocess
import sys
import threading
import time

# Optional: rumps for menubar (graceful fallback to tkinter)
try:
    import rumps
    HAS_RUMPS = True
except ImportError:
    HAS_RUMPS = False

from juhflow_crypto import (
    build_encrypted_packet,
    decrypt_payload,
    derive_aes_key,
    derive_shared_secret,
    generate_keypair,
    generate_node_id,
    parse_encrypted_packet,
)

logging.basicConfig(
    level=logging.INFO,
    format="[JuhFlow] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("juhflow")

# Ports (must match Linux juhflow_bridge.py)
BRIDGE_TCP_PORT = 59872
DISCOVERY_PORT = 59873
BEACON_INTERVAL = 3.0

# Edge detection (must match Linux overlay/flow/constants.py)
EDGE_THRESHOLD_PX = 5
EDGE_DWELL_MS = 150  # ms cursor must stay at edge
EDGE_COOLDOWN_MS = 1000  # ms after handoff before re-triggering

# Message types (must match Linux side)
MSG_HANDSHAKE = "handshake"
MSG_EDGE_HIT = "edge_hit"
MSG_CURSOR_WARP = "cursor_warp"
MSG_CLIPBOARD = "clipboard"
MSG_DEVICE_SWITCH = "device_switch"
MSG_HEARTBEAT = "heartbeat"

# Frame header
FRAME_HEADER_LEN = 4


def _send_framed(sock, data):
    sock.sendall(struct.pack('>I', len(data)) + data)


def _recv_framed(sock):
    header = b""
    while len(header) < FRAME_HEADER_LEN:
        chunk = sock.recv(FRAME_HEADER_LEN - len(header))
        if not chunk:
            return None
        header += chunk
    msg_len = struct.unpack('>I', header)[0]
    if msg_len > 1024 * 1024:
        return None
    data = b""
    while len(data) < msg_len:
        chunk = sock.recv(min(msg_len - len(data), 65536))
        if not chunk:
            return None
        data += chunk
    return data


class EdgeDetector:
    """Detect when mouse cursor hits screen edges on macOS.

    Uses Quartz CGEvent tap for efficient mouse tracking.
    Falls back to polling CGEvent.mouseLocation if tap fails.
    """

    def __init__(self, on_edge_hit=None):
        self.on_edge_hit = on_edge_hit
        self.running = False
        self.active = False  # only detect edges when Mac is the active machine
        self._thread = None
        self._suppressed_until = 0
        self._edge_start_time = 0
        self._current_edge = None

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Edge detector started (threshold=%dpx, dwell=%dms)",
                     EDGE_THRESHOLD_PX, EDGE_DWELL_MS)

    def stop(self):
        self.running = False

    def suppress_for(self, ms):
        self._suppressed_until = time.time() + ms / 1000.0

    def _poll_loop(self):
        """Poll mouse position to detect edge hits."""
        try:
            import Quartz
        except ImportError:
            logger.error("pyobjc-framework-Quartz not installed, edge detection disabled")
            return

        while self.running:
            time.sleep(0.016)  # ~60Hz polling

            if not self.active or time.time() < self._suppressed_until:
                self._current_edge = None
                continue

            # Get mouse position
            loc = Quartz.NSEvent.mouseLocation()
            mx, my_flipped = loc.x, loc.y

            # Get main screen bounds
            main_screen = Quartz.NSScreen.mainScreen()
            if not main_screen:
                continue
            frame = main_screen.frame()
            sw = frame.size.width
            sh = frame.size.height

            # NSScreen coordinates are bottom-left origin, convert
            my = sh - my_flipped

            # Detect edge
            edge = None
            if mx <= EDGE_THRESHOLD_PX:
                edge = "left"
            elif mx >= sw - EDGE_THRESHOLD_PX:
                edge = "right"
            elif my <= EDGE_THRESHOLD_PX:
                edge = "top"
            elif my >= sh - EDGE_THRESHOLD_PX:
                edge = "bottom"

            if edge:
                if edge == self._current_edge:
                    # Check dwell time
                    elapsed_ms = (time.time() - self._edge_start_time) * 1000
                    if elapsed_ms >= EDGE_DWELL_MS:
                        if self.on_edge_hit:
                            screen = {
                                "x": 0, "y": 0,
                                "width": int(sw), "height": int(sh),
                            }
                            self.on_edge_hit(edge, int(mx), int(my), screen)
                        self.suppress_for(EDGE_COOLDOWN_MS)
                        self._current_edge = None
                else:
                    self._current_edge = edge
                    self._edge_start_time = time.time()
            else:
                self._current_edge = None


class LinuxBridgeClient:
    """Encrypted TCP client connecting to JuhRadial MX on Linux."""

    def __init__(self, linux_ip, linux_port=BRIDGE_TCP_PORT,
                 on_message=None):
        self.linux_ip = linux_ip
        self.linux_port = linux_port
        self.on_message = on_message

        self._private_key, self._public_key_bytes = generate_keypair()
        self._node_id = generate_node_id()
        self._aes_key = None
        self._sock = None
        self._connected = threading.Event()
        self._running = False
        self._thread = None
        self._heartbeat_thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._connect_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._connected.clear()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    @property
    def connected(self):
        return self._connected.is_set()

    def send(self, msg):
        """Encrypt and send a message to Linux."""
        if not self._connected.is_set() or not self._sock or not self._aes_key:
            return False
        try:
            payload = json.dumps(msg).encode('utf-8')
            packet = build_encrypted_packet(self._node_id, self._aes_key, payload)
            _send_framed(self._sock, packet)
            return True
        except Exception:
            self._connected.clear()
            return False

    def _connect_loop(self):
        backoff = 1.0
        while self._running:
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(5.0)
                self._sock.connect((self.linux_ip, self.linux_port))

                # Plaintext handshake - exchange pubkeys
                handshake = {
                    "type": MSG_HANDSHAKE,
                    "public_key": self._public_key_bytes.hex(),
                    "hostname": socket.gethostname(),
                    "platform": "macos",
                    "node_id": self._node_id.hex(),
                    "software": "JuhFlow",
                }
                _send_framed(self._sock, json.dumps(handshake).encode('utf-8'))

                # Receive Linux handshake
                data = _recv_framed(self._sock)
                if not data:
                    raise ConnectionError("No handshake response")

                peer_handshake = json.loads(data.decode('utf-8'))
                peer_pubkey = bytes.fromhex(peer_handshake["public_key"])

                # Derive AES key
                shared_secret = derive_shared_secret(self._private_key, peer_pubkey)
                self._aes_key = derive_aes_key(shared_secret)

                logger.info("Connected to Linux: %s (%s)",
                            peer_handshake.get("hostname"), self.linux_ip)
                self._connected.set()
                backoff = 1.0

                # Start heartbeat
                self._heartbeat_thread = threading.Thread(
                    target=self._heartbeat_loop, daemon=True
                )
                self._heartbeat_thread.start()

                # Receive loop (encrypted)
                self._sock.settimeout(30.0)
                while self._running:
                    data = _recv_framed(self._sock)
                    if data is None:
                        break

                    parsed = parse_encrypted_packet(data)
                    if not parsed:
                        continue

                    _, nonce, tag, ciphertext = parsed
                    try:
                        plaintext = decrypt_payload(self._aes_key, nonce, tag, ciphertext)
                        msg = json.loads(plaintext.decode('utf-8'))
                        if msg.get("type") != MSG_HEARTBEAT and self.on_message:
                            self.on_message(msg)
                    except Exception as e:
                        logger.debug("Decrypt error: %s", e)

            except Exception as e:
                if self._running:
                    logger.debug("Connection to %s failed: %s", self.linux_ip, e)
            finally:
                self._connected.clear()
                if self._sock:
                    try:
                        self._sock.close()
                    except OSError:
                        pass
                    self._sock = None

            if not self._running:
                break

            for _ in range(int(backoff * 10)):
                if not self._running:
                    return
                time.sleep(0.1)
            backoff = min(backoff * 2, 30.0)

    def _heartbeat_loop(self):
        while self._running and self._connected.is_set():
            self.send({"type": MSG_HEARTBEAT, "ts": time.time()})
            for _ in range(50):
                if not self._running or not self._connected.is_set():
                    return
                time.sleep(0.1)


class DiscoveryListener:
    """Listen for JuhRadial MX Linux peers on LAN via UDP beacons."""

    def __init__(self, on_peer_found=None):
        self.on_peer_found = on_peer_found
        self.peers = {}
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _listen_loop(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', DISCOVERY_PORT))
            sock.settimeout(1.0)
        except OSError as e:
            logger.error("Cannot bind discovery port %d: %s", DISCOVERY_PORT, e)
            return

        logger.info("Listening for Linux peers on UDP %d", DISCOVERY_PORT)

        while self._running:
            try:
                data, addr = sock.recvfrom(4096)
                try:
                    msg = json.loads(data.decode('utf-8'))
                    if msg.get("software") == "JuhRadialMX":
                        peer_ip = msg.get("ip", addr[0])
                        if peer_ip not in self.peers:
                            logger.info("Discovered Linux peer: %s (%s)",
                                        msg.get("hostname"), peer_ip)
                        self.peers[peer_ip] = {
                            "hostname": msg.get("hostname"),
                            "port": msg.get("port", BRIDGE_TCP_PORT),
                            "public_key": msg.get("public_key"),
                            "last_seen": time.time(),
                        }
                        if self.on_peer_found:
                            self.on_peer_found(peer_ip, self.peers[peer_ip])
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
            except socket.timeout:
                continue

        sock.close()


class JuhFlowApp:
    """Main JuhFlow application controller."""

    def __init__(self):
        self.edge_detector = EdgeDetector(on_edge_hit=self._on_edge_hit)
        self.discovery = DiscoveryListener(on_peer_found=self._on_peer_found)
        self.bridge_client = None
        self._running = False
        self._linux_ip = None

    def start(self, linux_ip=None):
        """Start JuhFlow. If linux_ip provided, connect directly. Otherwise discover."""
        self._running = True

        # Start discovery
        self.discovery.start()

        # Start edge detection
        self.edge_detector.start()

        # Connect to known Linux IP if provided
        if linux_ip:
            self._connect_to_linux(linux_ip)

        logger.info("JuhFlow started - monitoring edges, discovering peers")

    def stop(self):
        self._running = False
        self.edge_detector.stop()
        self.discovery.stop()
        if self.bridge_client:
            self.bridge_client.stop()

    def _connect_to_linux(self, ip, port=BRIDGE_TCP_PORT):
        """Establish encrypted bridge to Linux JuhRadial MX."""
        if self.bridge_client:
            self.bridge_client.stop()
        self.bridge_client = LinuxBridgeClient(
            ip, port,
            on_message=self._on_linux_message,
        )
        self.bridge_client.start()
        self._linux_ip = ip

    def _on_peer_found(self, ip, peer_info):
        """Auto-connect to first discovered Linux peer."""
        if not self.bridge_client or not self.bridge_client.connected:
            logger.info("Auto-connecting to %s (%s)",
                        peer_info.get("hostname"), ip)
            self._connect_to_linux(ip, peer_info.get("port", BRIDGE_TCP_PORT))

    def _on_edge_hit(self, edge, mx, my, screen):
        """Forward edge hit to Linux."""
        if not self.bridge_client or not self.bridge_client.connected:
            logger.warning("Edge hit %s but bridge not connected", edge)
            return

        # Compute relative position
        sw, sh = screen["width"], screen["height"]
        if edge in ("left", "right"):
            relative_pos = my / sh if sh > 0 else 0.5
        else:
            relative_pos = mx / sw if sw > 0 else 0.5

        msg = {
            "type": MSG_EDGE_HIT,
            "edge": edge,
            "position": {"x": mx, "y": my},
            "relative_position": max(0.0, min(1.0, relative_pos)),
            "screen": screen,
            "timestamp": time.time(),
        }
        self.bridge_client.send(msg)
        # Deactivate edge detection - Linux is now the active machine
        self.edge_detector.active = False
        logger.info("Edge hit: %s at (%d, %d) -> sent to Linux (edge detect off)", edge, mx, my)

        # Also send clipboard
        self._sync_clipboard_to_linux()

    def _sync_clipboard_to_linux(self):
        """Send Mac clipboard content to Linux."""
        try:
            result = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=1,
            )
            if result.returncode == 0 and result.stdout:
                self.bridge_client.send({
                    "type": MSG_CLIPBOARD,
                    "content": result.stdout,
                    "content_type": "text/plain",
                })
        except Exception:
            pass

    def _on_linux_message(self, msg):
        """Handle messages from Linux JuhRadial MX."""
        msg_type = msg.get("type", "")

        if msg_type == MSG_CURSOR_WARP:
            self._warp_cursor(msg)
        elif msg_type == MSG_EDGE_HIT:
            self._handle_incoming_edge_hit(msg)
        elif msg_type == MSG_CLIPBOARD:
            self._handle_clipboard(msg)
        elif msg_type == MSG_DEVICE_SWITCH:
            logger.info("Device switch request: ch %s", msg.get("channel"))

    def _handle_incoming_edge_hit(self, msg):
        """Handle edge hit from Linux - warp cursor to opposite edge."""
        edge = msg.get("edge", "right")
        relative_pos = msg.get("relative_position", 0.5)

        opposite = {
            "left": "right", "right": "left",
            "top": "bottom", "bottom": "top",
        }
        arrival_edge = opposite.get(edge, "left")

        try:
            import Quartz
            main_screen = Quartz.NSScreen.mainScreen()
            frame = main_screen.frame()
            sw = int(frame.size.width)
            sh = int(frame.size.height)

            # Offset must be > EDGE_THRESHOLD_PX to avoid landing in the detection zone
            inset = EDGE_THRESHOLD_PX * 3  # 15px inside
            if arrival_edge == "left":
                x, y = inset, int(relative_pos * sh)
            elif arrival_edge == "right":
                x, y = sw - inset, int(relative_pos * sh)
            elif arrival_edge == "top":
                x, y = int(relative_pos * sw), inset
            else:
                x, y = int(relative_pos * sw), sh - inset

            Quartz.CGWarpMouseCursorPosition((x, y))
            self.edge_detector.suppress_for(EDGE_COOLDOWN_MS)
            # Activate edge detection - Mac is now the active machine
            self.edge_detector.active = True
            logger.info("Cursor warped to %s edge: (%d, %d) (edge detect on)", arrival_edge, x, y)
        except ImportError:
            logger.error("Quartz not available for cursor warp")

    def _warp_cursor(self, msg):
        """Warp cursor to absolute position."""
        try:
            import Quartz
            x = msg.get("x", 0)
            y = msg.get("y", 0)
            Quartz.CGWarpMouseCursorPosition((x, y))
            self.edge_detector.suppress_for(EDGE_COOLDOWN_MS)
        except ImportError:
            pass

    def _handle_clipboard(self, msg):
        """Set Mac clipboard from Linux content."""
        content = msg.get("content", "")
        if content:
            try:
                subprocess.run(
                    ["pbcopy"], input=content, text=True, timeout=1,
                )
                logger.info("Clipboard synced from Linux (%d chars)", len(content))
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Menubar app (rumps) or simple CLI
# ---------------------------------------------------------------------------

if HAS_RUMPS:
    class JuhFlowMenubar(rumps.App):
        """macOS menubar app for JuhFlow."""

        def __init__(self):
            super().__init__(
                "JuhFlow",
                icon=None,
                quit_button=None,
            )
            self.juhflow = JuhFlowApp()
            self._status_timer = None

            # Menu items
            self.menu = [
                rumps.MenuItem("Status: Searching...", callback=None),
                None,  # separator
                rumps.MenuItem("Start", callback=self._toggle),
                None,
                rumps.MenuItem("Quit", callback=self._quit),
            ]

        def _toggle(self, sender):
            if sender.title == "Start":
                self.juhflow.start()
                sender.title = "Stop"
                self.title = "JuhFlow"
            else:
                self.juhflow.stop()
                sender.title = "Start"
                self.title = "JuhFlow"

        def _quit(self, _):
            self.juhflow.stop()
            rumps.quit_application()

        @rumps.timer(2)
        def _update_status(self, _):
            if self.juhflow.bridge_client and self.juhflow.bridge_client.connected:
                status = f"Connected to {self.juhflow._linux_ip}"
                self.title = "JuhFlow"
            elif self.juhflow.discovery.peers:
                ip = next(iter(self.juhflow.discovery.peers))
                status = f"Found: {ip}, connecting..."
            else:
                status = "Searching for Linux..."
                self.title = "JuhFlow"

            self.menu["Status: Searching..."].title = status


def main():
    """Entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="JuhFlow - Mac companion for JuhRadial MX")
    parser.add_argument("--ip", help="Linux IP to connect to directly")
    parser.add_argument("--cli", action="store_true", help="Run without menubar GUI")
    args = parser.parse_args()

    if args.cli or not HAS_RUMPS:
        # CLI mode
        app = JuhFlowApp()
        app.start(linux_ip=args.ip)
        logger.info("Running in CLI mode. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
                if app.bridge_client and app.bridge_client.connected:
                    pass  # connected, running
                elif app.discovery.peers:
                    logger.info("Peers found: %s",
                                list(app.discovery.peers.keys()))
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            app.stop()
    else:
        # Menubar mode
        menubar = JuhFlowMenubar()
        menubar.juhflow.start(linux_ip=args.ip)
        menubar.run()


if __name__ == "__main__":
    main()
