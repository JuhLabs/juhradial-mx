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
import threading
import time

# Optional: rumps for menubar (graceful fallback to tkinter)
try:
    import rumps
    HAS_RUMPS = True
except ImportError:
    HAS_RUMPS = False

from flow_indicator import FlowIndicator

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
EDGE_DWELL_MS = 100  # ms cursor must stay at edge
EDGE_COOLDOWN_MS = 1000  # ms after handoff before re-triggering
EDGE_VELOCITY_INSTANT_PX_PER_S = 3000  # instant trigger if cursor hits edge this fast

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


class LogiAgent:
    """Communicate with Logi Options+ agent via its Unix socket IPC.

    Uses the agent's JSON-over-Unix-socket protocol to trigger Easy-Switch
    channel changes on Logitech devices (MX Master 4, MX Keys S, etc).
    """

    SOCKET_GLOB = "/tmp/logitech_kiros_agent-*"
    DEVICE_ID = "dev00000000"  # MX Master 4 (first device)

    def __init__(self):
        self._sock = None
        self._lock = threading.Lock()

    def _find_socket(self):
        import glob
        socks = glob.glob(self.SOCKET_GLOB)
        # Filter to actual sockets (not updater)
        for s in socks:
            if "updater" not in s:
                return s
        return None

    def _connect(self):
        if self._sock:
            return True
        sock_path = self._find_socket()
        if not sock_path:
            logger.debug("Logi agent socket not found")
            return False
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(5)
            self._sock.connect(sock_path)
            # Read initial handshake frame (4-byte start)
            self._sock.recv(4)
            # Read the server's initial protobuf messages
            self._read_frame()  # "protobuf" subprotocol
            self._read_frame()  # OPTIONS / message
            return True
        except Exception as e:
            logger.debug("Logi agent connect failed: %s", e)
            self._sock = None
            return False

    def _read_frame(self):
        header = b""
        while len(header) < 4:
            chunk = self._sock.recv(4 - len(header))
            if not chunk:
                return None
            header += chunk
        frame_len = struct.unpack('>I', header)[0]
        body = b""
        while len(body) < frame_len:
            chunk = self._sock.recv(frame_len - len(body))
            if not chunk:
                return None
            body += chunk
        return body

    def _send_json(self, msg):
        json_bytes = json.dumps(msg).encode('utf-8')
        proto_name = b"json"
        total_size = len(proto_name) + len(json_bytes) + 8
        frame = (struct.pack('<I', total_size) +
                 struct.pack('>I', len(proto_name)) + proto_name +
                 struct.pack('>I', len(json_bytes)) + json_bytes)
        self._sock.sendall(frame)

    def _recv_json(self, timeout=5):
        self._sock.settimeout(timeout)
        # skip 4-byte start marker
        self._sock.recv(4)
        proto_len = struct.unpack('>I', self._sock.recv(4))[0]
        proto_name = self._sock.recv(proto_len).decode('ascii')
        msg_len = struct.unpack('>I', self._sock.recv(4))[0]
        msg_data = b""
        while len(msg_data) < msg_len:
            msg_data += self._sock.recv(msg_len - len(msg_data))
        if proto_name == "json":
            return json.loads(msg_data)
        return None

    def switch_channel(self, channel):
        """Switch MX Master 4 Easy-Switch to given channel (1-based).

        Sends the HID++ ChangeHost command via the Logi Options+ agent.
        Payload: {"@type": "...devices.ChangeHost", "host": <0-based index>}
        """
        host_index = channel - 1  # change_host uses 0-based index
        with self._lock:
            self._disconnect()
            if not self._connect():
                logger.warning("Cannot switch Easy-Switch: Logi agent not available")
                return False
            try:
                self._send_json({
                    "msgId": "juhflow-ch",
                    "verb": "set",
                    "path": f"/change_host/{self.DEVICE_ID}/host",
                    "payload": {
                        "@type": "type.googleapis.com/logi.protocol.devices.ChangeHost",
                        "host": host_index,
                    }
                })
                resp = self._recv_json(timeout=3)
                code = resp.get("result", {}).get("code") if resp else "no response"
                if code == "SUCCESS":
                    logger.info("Easy-Switch: switched to host %d (ch%d)", host_index, channel)
                    return True
                else:
                    logger.warning("Easy-Switch change_host failed: %s", code)
                    return False
            except Exception as e:
                logger.warning("Easy-Switch error: %s", e)
                return False
            finally:
                self._disconnect()

    def _disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


class EdgeDetector:
    """Detect when mouse cursor hits screen edges on macOS.

    Uses Quartz CGEvent tap for efficient mouse tracking.
    Falls back to polling CGEvent.mouseLocation if tap fails.
    """

    def __init__(self, on_edge_hit=None, watch_edge=None):
        self.on_edge_hit = on_edge_hit
        self.watch_edge = watch_edge  # only detect this specific edge
        self.running = False
        self.active = True
        self._thread = None
        self._suppressed_until = 0
        self._edge_start_time = 0
        self._current_edge = None
        self._prev_pos = None
        self._prev_time = 0

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
            time.sleep(0.008)  # ~120Hz polling

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

            # Velocity tracking
            now = time.time()
            velocity = 0.0
            if self._prev_pos is not None and now > self._prev_time:
                dx = mx - self._prev_pos[0]
                dy = my - self._prev_pos[1]
                dt = now - self._prev_time
                velocity = (dx * dx + dy * dy) ** 0.5 / dt
            self._prev_pos = (mx, my)
            self._prev_time = now

            # Detect only the watched edge
            edge = None
            if self.watch_edge == "right" and mx >= sw - EDGE_THRESHOLD_PX:
                edge = "right"
            elif self.watch_edge == "left" and mx <= EDGE_THRESHOLD_PX:
                edge = "left"
            elif self.watch_edge == "top" and my <= EDGE_THRESHOLD_PX:
                edge = "top"
            elif self.watch_edge == "bottom" and my >= sh - EDGE_THRESHOLD_PX:
                edge = "bottom"

            # Debug: log when near the watched edge
            if self.watch_edge == "right" and mx >= sw - 50:
                if not hasattr(self, '_last_debug') or time.time() - self._last_debug > 2:
                    logger.debug("Near right edge: mx=%.0f, threshold=%d, sw=%.0f", mx, sw - EDGE_THRESHOLD_PX, sw)
                    self._last_debug = time.time()

            if edge:
                # Instant trigger if cursor hits edge at high velocity
                if velocity >= EDGE_VELOCITY_INSTANT_PX_PER_S:
                    if self.on_edge_hit:
                        screen = {
                            "x": 0, "y": 0,
                            "width": int(sw), "height": int(sh),
                        }
                        self.on_edge_hit(edge, int(mx), int(my), screen)
                    self.suppress_for(EDGE_COOLDOWN_MS)
                    self._current_edge = None
                    continue

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
                 on_message=None, on_connect=None, on_disconnect=None):
        self.linux_ip = linux_ip
        self.linux_port = linux_port
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

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
                self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
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
                if self.on_connect:
                    self.on_connect()
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
                was_connected = self._connected.is_set()
                self._connected.clear()
                if was_connected and self.on_disconnect:
                    self.on_disconnect()
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
            sock.bind(('0.0.0.0', DISCOVERY_PORT))  # nosec B104 - LAN broadcast receiver, must bind all interfaces
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

    OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}

    def __init__(self, linux_direction="right", mac_channel=1, linux_channel=2):
        """
        linux_direction: which edge Linux is on (left/right/top/bottom).
        mac_channel: MX Easy-Switch channel for this Mac (1-3).
        linux_channel: MX Easy-Switch channel for the Linux machine (1-3).
        """
        self.linux_direction = linux_direction
        self.mac_arrival_edge = linux_direction  # cursor arrives from the same side Linux is on
        self.mac_channel = mac_channel
        self.linux_channel = linux_channel
        self.edge_detector = EdgeDetector(on_edge_hit=self._on_edge_hit, watch_edge=linux_direction)
        self.discovery = DiscoveryListener(on_peer_found=self._on_peer_found)
        self.bridge_client = None
        self.logi_agent = LogiAgent()
        self.indicator = FlowIndicator(edge=linux_direction)
        self._running = False
        self._linux_ip = None
        self._cursor_on_mac = False
        self._sent_to_linux_at = 0
        logger.info("Layout: Linux is on the %s | Easy-Switch: Mac=ch%d Linux=ch%d",
                     linux_direction, mac_channel, linux_channel)

    def start(self, linux_ip=None):
        """Start JuhFlow. If linux_ip provided, connect directly. Otherwise discover."""
        self._running = True

        # Start discovery
        self.discovery.start()

        # Start edge detection
        self.edge_detector.start()

        # Start global hotkey listener (Ctrl+Shift+Arrow to switch)
        self._start_hotkey_listener()

        # Connect to known Linux IP if provided
        if linux_ip:
            self._connect_to_linux(linux_ip)

        logger.info("JuhFlow started - edges + hotkey (Ctrl+Shift+Arrow) + discovery")

    def stop(self):
        self._running = False
        self.edge_detector.stop()
        self.discovery.stop()
        self.indicator.hide()
        if self.bridge_client:
            self.bridge_client.stop()

    def _start_hotkey_listener(self):
        """Listen for Ctrl+Shift+Arrow to switch machines."""
        def _listener():
            try:
                import Quartz
                from Quartz import (
                    CGEventTapCreate, kCGSessionEventTap,
                    kCGHeadInsertEventTap, kCGEventTapOptionListenOnly,
                    CGEventMaskBit, kCGEventKeyDown, CGEventGetIntegerValueField,
                    kCGKeyboardEventKeycode, CFMachPortCreateRunLoopSource,
                    CFRunLoopGetCurrent, CFRunLoopAddSource, kCFRunLoopDefaultMode,
                    CFRunLoopRun,
                )
            except ImportError:
                logger.error("Quartz not available for hotkey listener")
                return

            # Arrow keycodes: left=123, right=124, up=126, down=125
            ARROW_TO_DIRECTION = {123: "left", 124: "right", 126: "top", 125: "bottom"}

            def callback(proxy, event_type, event, refcon):
                flags = Quartz.CGEventGetFlags(event)
                ctrl = (flags & Quartz.kCGEventFlagMaskControl) != 0
                shift = (flags & Quartz.kCGEventFlagMaskShift) != 0
                if ctrl and shift:
                    keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                    if keycode in ARROW_TO_DIRECTION:
                        direction = ARROW_TO_DIRECTION[keycode]
                        if direction == self.linux_direction:
                            logger.info("Hotkey: Ctrl+Shift+%s -> switch to Linux", direction)
                            self.switch_to_linux()
                return event

            tap = CGEventTapCreate(
                kCGSessionEventTap, kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly,
                CGEventMaskBit(kCGEventKeyDown),
                callback, None,
            )
            if not tap:
                logger.error("Failed to create event tap for hotkeys (check Accessibility permissions)")
                return

            src = CFMachPortCreateRunLoopSource(None, tap, 0)
            CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopDefaultMode)
            logger.info("Hotkey listener active: Ctrl+Shift+Arrow to switch")
            CFRunLoopRun()

        threading.Thread(target=_listener, daemon=True).start()

    def switch_to_linux(self):
        """Send edge_hit + device_switch to Linux."""
        if not self.bridge_client or not self.bridge_client.connected:
            logger.warning("Cannot switch: not connected to Linux")
            return

        try:
            import Quartz
            loc = Quartz.NSEvent.mouseLocation()
            screen = Quartz.NSScreen.mainScreen().frame()
            sw, sh = int(screen.size.width), int(screen.size.height)
            mx, my = int(loc.x), int(sh - loc.y)
        except ImportError:
            mx, my, sw, sh = 0, 0, 1920, 1080

        if self.linux_direction in ("left", "right"):
            relative_pos = my / sh if sh > 0 else 0.5
        else:
            relative_pos = mx / sw if sw > 0 else 0.5

        self.bridge_client.send({
            "type": MSG_EDGE_HIT,
            "edge": self.linux_direction,
            "position": {"x": mx, "y": my},
            "relative_position": max(0.0, min(1.0, relative_pos)),
            "screen": {"x": 0, "y": 0, "width": sw, "height": sh},
            "timestamp": time.time(),
        })
        self._cursor_on_mac = False
        self._sent_to_linux_at = time.time()
        self.edge_detector.suppress_for(3000)
        logger.info("Switching to Linux (ch%d)...", self.linux_channel)
        self._sync_clipboard_to_linux()
        # Switch MX Master 4 Easy-Switch + toggle BT to release BLE connection
        threading.Thread(target=self._switch_away_from_mac, daemon=True).start()

    def _switch_away_from_mac(self):
        """Send Easy-Switch ChangeHost command, toggle BT off briefly as insurance."""
        # Step 1: Send HID++ ChangeHost via Logi agent
        ok = self.logi_agent.switch_channel(self.linux_channel)
        if not ok:
            logger.warning("Easy-Switch command failed, trying BT toggle anyway")
        # Step 2: Brief BT toggle to ensure Mac doesn't auto-reconnect
        time.sleep(0.2)
        try:
            subprocess.run(["blueutil", "--power", "0"], timeout=5)
            time.sleep(1.5)
            subprocess.run(["blueutil", "--power", "1"], timeout=5)
            logger.info("Bluetooth toggled to release BLE")
        except Exception as e:
            logger.warning("blueutil toggle failed: %s", e)

    def _connect_to_linux(self, ip, port=BRIDGE_TCP_PORT):
        """Establish encrypted bridge to Linux JuhRadial MX."""
        if self.bridge_client:
            self.bridge_client.stop()
        self.bridge_client = LinuxBridgeClient(
            ip, port,
            on_message=self._on_linux_message,
            on_connect=lambda: self.indicator.show(),
            on_disconnect=lambda: self.indicator.hide(),
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
        """Forward edge hit to Linux (only on the configured edge)."""
        if edge != self.linux_direction:
            return
        logger.info("Edge hit: %s at (%d, %d)", edge, mx, my)
        self.edge_detector.active = False
        self.switch_to_linux()

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
            channel = msg.get("channel")
            logger.info("Device switch request from Linux: ch %s", channel)
            if channel == self.mac_channel:
                # Switching TO Mac - ensure BT is on for reconnection
                threading.Thread(target=self._ensure_bt_on, daemon=True).start()
            elif channel == self.linux_channel:
                # Switching TO Linux - send command + toggle BT
                threading.Thread(target=self._switch_away_from_mac, daemon=True).start()

    def _handle_incoming_edge_hit(self, msg):
        """Handle edge hit from Linux - warp cursor to opposite edge."""
        if self._cursor_on_mac:
            return  # cursor already on Mac, ignore repeated warps from Linux
        # Grace period after sending cursor to Linux - ignore stale Linux edge_hits
        if time.time() - self._sent_to_linux_at < 3.0:
            return

        relative_pos = msg.get("relative_position", 0.5)
        arrival_edge = self.mac_arrival_edge  # always arrive on the edge facing Linux

        try:
            import Quartz
            main_screen = Quartz.NSScreen.mainScreen()
            frame = main_screen.frame()
            sw = int(frame.size.width)
            sh = int(frame.size.height)

            if arrival_edge == "left":
                x, y = 15, int(relative_pos * sh)
            elif arrival_edge == "right":
                x, y = sw - 15, int(relative_pos * sh)
            elif arrival_edge == "top":
                x, y = int(relative_pos * sw), 15
            else:
                x, y = int(relative_pos * sw), sh - 15

            Quartz.CGWarpMouseCursorPosition((x, y))
            self._cursor_on_mac = True  # cursor is now on Mac, block further warps
            self.edge_detector.suppress_for(EDGE_COOLDOWN_MS)
            self.edge_detector.active = True
            logger.info("Cursor warped to %s edge: (%d, %d) - switching to Mac ch%d",
                         arrival_edge, x, y, self.mac_channel)
            # Ensure Bluetooth is on so device can reconnect to Mac
            # (Linux side handles sending ChangeHost via Bolt receiver)
            threading.Thread(target=self._ensure_bt_on, daemon=True).start()
        except ImportError:
            logger.error("Quartz not available for cursor warp")

    def _ensure_bt_on(self):
        """Make sure Bluetooth is powered on for BLE reconnection."""
        try:
            result = subprocess.run(["blueutil", "--power"], capture_output=True, text=True, timeout=5)
            if result.stdout.strip() == "0":
                logger.info("Turning Bluetooth back on for Mac reconnection...")
                subprocess.run(["blueutil", "--power", "1"], timeout=5)
        except Exception as e:
            logger.warning("blueutil check/restore failed: %s", e)

    def _warp_cursor(self, msg):
        """Warp cursor to absolute position."""
        if self._cursor_on_mac or time.time() - self._sent_to_linux_at < 3.0:
            return
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
    parser.add_argument("--direction", default="right",
                        choices=["left", "right", "top", "bottom"],
                        help="Which edge Linux is on (default: right)")
    parser.add_argument("--mac-channel", type=int, default=1,
                        help="MX Easy-Switch channel for this Mac (1-3)")
    parser.add_argument("--linux-channel", type=int, default=2,
                        help="MX Easy-Switch channel for Linux (1-3)")
    args = parser.parse_args()

    if args.cli or not HAS_RUMPS:
        # CLI mode - need NSApplication event loop for overlay indicator
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
            ns_app = NSApplication.sharedApplication()
            ns_app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        except ImportError:
            ns_app = None

        app = JuhFlowApp(linux_direction=args.direction,
                         mac_channel=args.mac_channel,
                         linux_channel=args.linux_channel)
        app.start(linux_ip=args.ip)
        logger.info("Running in CLI mode. Press Ctrl+C to stop.")

        if ns_app:
            # Run AppKit event loop on main thread (required for overlay windows)
            # Use a timer to check for KeyboardInterrupt periodically
            import signal
            _shutdown = threading.Event()

            def _sigint(sig, frame):
                logger.info("Shutting down...")
                app.stop()
                _shutdown.set()
                ns_app.terminate_(None)

            signal.signal(signal.SIGINT, _sigint)
            signal.signal(signal.SIGTERM, _sigint)
            ns_app.run()
        else:
            try:
                while True:
                    time.sleep(1)
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
