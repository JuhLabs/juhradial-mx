"""Cursor handoff orchestrator - connects edge detection to presence channel.

When cursor hits a screen edge mapped to a peer, sends cursor_handoff and
clipboard_sync messages via the encrypted presence channel, then receives
handoffs from peers and warps cursor to the arrival position.
"""

import json
import logging
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .constants import (
    LOGI_PRESENCE_PORT,
    MSG_CURSOR_HANDOFF,
    MSG_CLIPBOARD_SYNC,
)

logger = logging.getLogger("juhradial.flow.handoff")

_CFG_PATH = Path.home() / ".config" / "juhradial" / "config.json"

# Map edge -> opposite edge for receiving handoffs
OPPOSITE_EDGE = {
    "left": "right",
    "right": "left",
    "top": "bottom",
    "bottom": "top",
}

class FlowHandoffManager:
    """Orchestrates cursor handoff between machines.

    Connects: edge detector -> presence clients / juhflow bridge -> cursor warp
    """

    def __init__(self, edge_detector=None, presence_server=None,
                 juhflow_bridge=None):
        self.edge_detector = edge_detector
        self.presence_server = presence_server
        self.juhflow_bridge = juhflow_bridge

        # {peer_name: FlowPresenceClient}
        self.presence_clients: Dict[str, 'FlowPresenceClient'] = {}
        self._clients_lock = threading.Lock()

        # {peer_name: edge} - which edge each peer is assigned to
        self.peer_edges: Dict[str, str] = {}

        # Cached flow config (avoid re-reading config.json on every edge hit)
        self._flow_config_cache: Optional[dict] = None
        self._flow_config_mtime: float = 0.0

        # Cached flow monitor geometry (set from main thread, used from any thread)
        self._flow_monitor_screen: Optional[dict] = None

        # Active warp timers (cancelled on new handoff to prevent cursor fighting)
        self._warp_timers: List[threading.Timer] = []
        self._warp_lock = threading.Lock()

        # Wire edge detector callback
        if edge_detector:
            edge_detector.on_edge_hit = self.on_edge_hit

        # Wire presence server message callback
        if presence_server:
            presence_server.on_message = self._on_server_message

    def cache_flow_monitor_geometry(self):
        """Cache flow monitor geometry from Qt (call from main thread)."""
        cfg = self.get_flow_config()
        monitor_name = cfg.get("monitor", "")
        if not monitor_name:
            return
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                for s in app.screens():
                    if s.name() == monitor_name:
                        g = s.geometry()
                        self._flow_monitor_screen = {
                            "x": g.x(), "y": g.y(),
                            "width": g.width(), "height": g.height(),
                        }
                        logger.info("Cached flow monitor %s: %s",
                                    monitor_name, self._flow_monitor_screen)
                        return
        except Exception as e:
            logger.debug("Qt monitor cache failed: %s", e)
        # Fallback: parse xrandr
        self._flow_monitor_screen = self._xrandr_monitor_geometry(monitor_name)
        if self._flow_monitor_screen:
            logger.info("Cached flow monitor %s via xrandr: %s",
                        monitor_name, self._flow_monitor_screen)

    @staticmethod
    def _xrandr_monitor_geometry(monitor_name: str) -> Optional[dict]:
        """Get monitor geometry from xrandr (thread-safe, no Qt needed)."""
        try:
            result = subprocess.run(
                ["xrandr", "--query"],
                capture_output=True, text=True, timeout=2.0,
            )
            for line in result.stdout.splitlines():
                if line.startswith(monitor_name + " ") and " connected" in line:
                    for part in line.split():
                        if "x" in part and "+" in part:
                            # e.g. "3840x2160+1920+0"
                            wxh, rest = part.split("+", 1)
                            px, py = rest.split("+", 1)
                            w, h = wxh.split("x")
                            return {
                                "x": int(px), "y": int(py),
                                "width": int(w), "height": int(h),
                            }
        except Exception as e:
            logger.debug("xrandr monitor lookup failed: %s", e)
        return None

    def _get_flow_monitor_screen(self) -> Optional[dict]:
        """Get flow monitor geometry (thread-safe).

        Uses cached value from main-thread init, falls back to xrandr.
        """
        if self._flow_monitor_screen:
            return self._flow_monitor_screen
        # Cache miss - try xrandr (works from any thread)
        cfg = self.get_flow_config()
        monitor_name = cfg.get("monitor", "")
        if monitor_name:
            screen = self._xrandr_monitor_geometry(monitor_name)
            if screen:
                self._flow_monitor_screen = screen
                return screen
        return None

    def connect_to_peer(self, peer_name: str, peer_ip: str, peer_port: int,
                        our_node_id: bytes, peer_aes_key: bytes):
        """Establish outgoing presence connection to a peer."""
        from .logi_presence import FlowPresenceClient

        client = FlowPresenceClient(
            peer_ip=peer_ip,
            peer_port=LOGI_PRESENCE_PORT,
            our_node_id=our_node_id,
            peer_aes_key=peer_aes_key,
            on_message=lambda msg: self._on_client_message(peer_name, msg),
        )
        with self._clients_lock:
            # Stop existing client if any
            old = self.presence_clients.get(peer_name)
            if old:
                old.stop()
            self.presence_clients[peer_name] = client
        client.start()
        logger.info("Connecting presence client to %s (%s:%d)", peer_name, peer_ip, peer_port)

    def set_peer_edge(self, peer_name: str, edge: str):
        """Set which screen edge a peer is mapped to."""
        self.peer_edges[peer_name] = edge
        logger.info("Peer %s mapped to %s edge", peer_name, edge)

    def stop(self):
        """Stop all presence clients."""
        with self._clients_lock:
            for name, client in self.presence_clients.items():
                client.stop()
            self.presence_clients.clear()

    def on_edge_hit(self, edge: str, cx: int, cy: int, screen: dict):
        """Called when cursor hits a screen edge.

        Finds which peer is configured for this edge, computes relative
        position, and sends cursor_handoff + clipboard_sync via presence
        channel or JuhFlow bridge.
        """
        # Compute relative position along the edge (0.0 - 1.0)
        sx, sy = screen["x"], screen["y"]
        sw, sh = screen["width"], screen["height"]

        if edge in ("left", "right"):
            relative_pos = (cy - sy) / sh if sh > 0 else 0.5
        else:
            relative_pos = (cx - sx) / sw if sw > 0 else 0.5

        relative_pos = max(0.0, min(1.0, relative_pos))

        # Find presence peer for this edge
        peer_name = None
        for name, peer_edge in self.peer_edges.items():
            if peer_edge == edge:
                peer_name = name
                break

        sent = False
        if peer_name:
            # Send via presence channel (paired JuhRadialMX peers)
            handoff_msg = {
                "type": MSG_CURSOR_HANDOFF,
                "edge": edge,
                "relative_position": relative_pos,
                "screen_width": sw,
                "screen_height": sh,
            }
            sent = self._send_to_peer(peer_name, handoff_msg)
            if sent:
                logger.info("Cursor handoff to %s via %s edge (rel: %.2f)",
                            peer_name, edge, relative_pos)

        # Also send to JuhFlow bridge peers (Mac/Win companion apps)
        # Only on the configured flow direction edge
        cfg = self.get_flow_config()
        flow_direction = cfg.get("direction", "right")
        if (self.juhflow_bridge and self.juhflow_bridge.get_peers()
                and edge == flow_direction):
            self.juhflow_bridge.send_edge_hit(
                edge, (cx, cy), screen,
                relative_position=relative_pos,
            )
            sent = True
            logger.info("Edge hit forwarded to JuhFlow bridge peers: %s (rel: %.2f)",
                        edge, relative_pos)
            # Switch MX Master to the Mac's Easy-Switch host channel
            self._switch_host_for_bridge()

        if not sent:
            logger.debug("No peer configured for %s edge", edge)
            return

        # Send clipboard content to whichever channel delivered
        self._sync_clipboard(peer_name)

    def _sync_clipboard(self, peer_name: Optional[str] = None):
        """Sync clipboard to peer via presence or bridge."""
        try:
            from .clipboard import get_clipboard
            clipboard_content = get_clipboard()
            if not clipboard_content:
                return

            # Send to presence peer if specified
            if peer_name:
                clipboard_msg = {
                    "type": MSG_CLIPBOARD_SYNC,
                    "content": clipboard_content,
                }
                self._send_to_peer(peer_name, clipboard_msg)

            # Send to bridge peers
            if self.juhflow_bridge and self.juhflow_bridge.get_peers():
                self.juhflow_bridge.send_clipboard(clipboard_content)

        except Exception as e:
            logger.debug("Clipboard sync failed: %s", e)

    def _on_client_message(self, peer_name: str, message: dict):
        """Handle message received from outgoing presence client."""
        self._dispatch_message(peer_name, message)

    def _on_server_message(self, peer_name: str, message: dict):
        """Handle message received on incoming presence server connection."""
        self._dispatch_message(peer_name, message)

    def _dispatch_message(self, peer_name: str, message: dict):
        """Route received messages by type."""
        msg_type = message.get("type", "")

        if msg_type == MSG_CURSOR_HANDOFF:
            self.handle_cursor_handoff(peer_name, message)
        elif msg_type == MSG_CLIPBOARD_SYNC:
            self._handle_clipboard_sync(peer_name, message)
        # Heartbeats are silently ignored

    def handle_cursor_handoff(self, peer_name: str, message: dict):
        """Handle incoming cursor handoff - warp cursor to arrival position.

        Places cursor at center-x of the flow monitor to avoid edge re-triggering.
        Warps repeatedly over 3s to survive MX Master Bolt reconnection race.
        """
        relative_pos = message.get("relative_position", 0.5)
        logger.info("Handoff received from %s: rel=%.2f", peer_name, relative_pos)

        # Suppress edge detector during cursor warp sequence to prevent bounce-back.
        # Warps run for 3s (6 x 0.5s), then we clear suppression after 3.5s.
        # 5s ceiling as safety fallback in case the clear timer doesn't fire.
        if self.edge_detector:
            self.edge_detector.suppress_for(5000)
            logger.debug("Edge detector suppressed (cleared after warps complete)")

        try:
            from overlay.overlay_cursor import warp_cursor
        except ImportError:
            from overlay_cursor import warp_cursor

        # Get flow monitor geometry (cached from main thread at startup)
        screen = self._get_flow_monitor_screen()
        if not screen:
            logger.error("No flow monitor geometry - cannot warp cursor")
            return
        sx, sy = screen["x"], screen["y"]
        sw, sh = screen["width"], screen["height"]

        # Place cursor at center-x of the flow monitor, relative-y along the edge.
        # Center-x avoids re-triggering the edge detector on arrival.
        x = sx + sw // 2
        y = sy + int(relative_pos * sh)
        # Clamp y to stay within screen
        y = max(sy + 50, min(sy + sh - 50, y))
        logger.info("Warp target: (%d, %d) center of %dx%d+%d+%d", x, y, sw, sh, sx, sy)

        # Cancel any in-flight warp timers from a previous handoff
        # to prevent cursor position fighting.
        with self._warp_lock:
            for old_timer in self._warp_timers:
                old_timer.cancel()
            self._warp_timers.clear()

        # Warp cursor repeatedly to survive the MX Master device reconnection.
        # When the device switches back to Linux via the Mac companion, the Bolt
        # receiver reconnection can reset/move the cursor. We keep re-warping
        # for 3 seconds to ensure the cursor lands at the right spot.
        def _do_warp(attempt):
            success = warp_cursor(x, y)
            if attempt == 0:
                logger.info("Warp #%d: (%d, %d) -> %s", attempt, x, y,
                            "OK" if success else "FAILED")

        _do_warp(0)
        new_timers = []
        for i in range(1, 7):
            t = threading.Timer(i * 0.5, _do_warp, args=[i])
            t.daemon = True
            t.start()
            new_timers.append(t)

        # Clear suppression 0.5s after last warp so user can transfer again
        def _end_suppression():
            if self.edge_detector:
                self.edge_detector._suppress_until = 0.0
                logger.debug("Edge suppression cleared (warps complete)")

        end_timer = threading.Timer(3.5, _end_suppression)
        end_timer.daemon = True
        end_timer.start()
        new_timers.append(end_timer)

        with self._warp_lock:
            self._warp_timers = new_timers

    def _handle_clipboard_sync(self, peer_name: str, message: dict):
        """Handle incoming clipboard sync."""
        content = message.get("content", "")
        if content:
            from .clipboard import set_clipboard
            set_clipboard(content)
            logger.info("Clipboard synced from %s (%d chars)", peer_name, len(content))

    def _send_to_peer(self, peer_name: str, message: dict) -> bool:
        """Send message via presence client (outgoing) or server (incoming)."""
        # Try outgoing client first
        with self._clients_lock:
            client = self.presence_clients.get(peer_name)
        if client and client.send_message(message):
            return True

        # Fall back to server (incoming connection)
        if self.presence_server:
            return self.presence_server.send_to_peer(peer_name, message)

        return False

    def get_flow_config(self):
        """Read flow config from config.json (cached, reloads on file change)."""
        try:
            cfg_path = _CFG_PATH
            if cfg_path.exists():
                mtime = cfg_path.stat().st_mtime
                if self._flow_config_cache is None or mtime != self._flow_config_mtime:
                    self._flow_config_cache = json.loads(cfg_path.read_text()).get("flow", {})
                    self._flow_config_mtime = mtime
                return self._flow_config_cache
        except Exception:
            pass
        return {}

    def _switch_host_for_bridge(self):
        """Switch MX Master to the Mac/Win host via D-Bus Easy-Switch."""
        cfg = self.get_flow_config()
        remote_host = cfg.get("remote_host_index")
        if remote_host is None:
            logger.debug("No remote_host_index in flow config, skipping host switch")
            return
        self._dbus_set_host(int(remote_host))

    def switch_host_to_linux(self):
        """Switch MX Master back to this Linux host via D-Bus Easy-Switch."""
        cfg = self.get_flow_config()
        local_host = cfg.get("local_host_index")
        if local_host is None:
            logger.debug("No local_host_index in flow config, skipping host switch")
            return
        self._dbus_set_host(int(local_host))

    def _dbus_set_host(self, host_index: int):
        """Call the daemon's SetHost D-Bus method to switch Easy-Switch channel.

        Uses Popen (fire-and-forget) to avoid blocking the handoff critical path.
        """
        try:
            import subprocess
            subprocess.Popen(
                [
                    "gdbus", "call", "--session",
                    "--dest", "org.kde.juhradialmx",
                    "--object-path", "/org/kde/juhradialmx/Daemon",
                    "--method", "org.kde.juhradialmx.Daemon.SetHost",
                    str(host_index),
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            logger.info("SetHost %d dispatched (async)", host_index)
        except Exception as e:
            logger.warning("Host switch D-Bus call failed: %s", e)
