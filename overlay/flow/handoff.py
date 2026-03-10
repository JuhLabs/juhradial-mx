"""Cursor handoff orchestrator - connects edge detection to presence channel.

When cursor hits a screen edge mapped to a peer, sends cursor_handoff and
clipboard_sync messages via the encrypted presence channel, then receives
handoffs from peers and warps cursor to the arrival position.
"""

import json
import logging
import threading
from typing import Dict, Optional

from .constants import (
    LOGI_PRESENCE_PORT,
    MSG_CURSOR_HANDOFF,
    MSG_CLIPBOARD_SYNC,
)

logger = logging.getLogger("juhradial.flow.handoff")

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

        # Wire edge detector callback
        if edge_detector:
            edge_detector.on_edge_hit = self.on_edge_hit

        # Wire presence server message callback
        if presence_server:
            presence_server.on_message = self._on_server_message

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
        cfg = self._get_flow_config()
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
            import subprocess
            result = subprocess.run(
                ["wl-paste", "--no-newline"],
                capture_output=True, text=True, timeout=1,
            )
            clipboard_content = result.stdout if result.returncode == 0 else ""
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
            self._handle_cursor_handoff(peer_name, message)
        elif msg_type == MSG_CLIPBOARD_SYNC:
            self._handle_clipboard_sync(peer_name, message)
        # Heartbeats are silently ignored

    def _handle_cursor_handoff(self, peer_name: str, message: dict):
        """Handle incoming cursor handoff - warp cursor to arrival position."""
        edge = message.get("edge", "right")
        relative_pos = message.get("relative_position", 0.5)
        arrival_edge = OPPOSITE_EDGE.get(edge, "left")

        # Get our screen geometry
        try:
            from overlay.overlay_cursor import get_screen_geometry, warp_cursor
        except ImportError:
            from overlay_cursor import get_screen_geometry, warp_cursor
        screen = get_screen_geometry()
        sx, sy = screen["x"], screen["y"]
        sw, sh = screen["width"], screen["height"]

        # Compute arrival position on opposite edge
        # Warp cursor well inside the screen so it doesn't land on/near the
        # indicator and accidentally re-trigger a switch back.
        inset = 80  # 80px inside from the edge
        if arrival_edge == "left":
            x = sx + inset
            y = sy + int(relative_pos * sh)
        elif arrival_edge == "right":
            x = sx + sw - inset
            y = sy + int(relative_pos * sh)
        elif arrival_edge == "top":
            x = sx + int(relative_pos * sw)
            y = sy + inset
        elif arrival_edge == "bottom":
            x = sx + int(relative_pos * sw)
            y = sy + sh - inset
        else:
            x = sx + sw // 2
            y = sy + sh // 2

        # Suppress edge detector to prevent immediate bounce-back.
        # Use a longer cooldown (3s) since cursor arrives right at the edge
        # and the user needs time to move away from the indicator zone.
        if self.edge_detector:
            self.edge_detector.suppress_for(3000)

        # Switch MX Master back to this host (Linux)
        self._switch_host_to_linux()

        # Haptic feedback on arrival
        try:
            import subprocess
            subprocess.Popen(
                ["gdbus", "call", "--session",
                 "--dest", "org.kde.juhradialmx",
                 "--object-path", "/org/kde/juhradialmx/Daemon",
                 "--method", "org.kde.juhradialmx.Daemon.TriggerHaptic",
                 "confirm"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

        # Warp cursor
        success = warp_cursor(x, y)
        logger.info(
            "Cursor arrival from %s: %s edge -> (%d, %d) [%s]",
            peer_name, arrival_edge, x, y, "ok" if success else "failed",
        )

    def _handle_clipboard_sync(self, peer_name: str, message: dict):
        """Handle incoming clipboard sync."""
        content = message.get("content", "")
        if content:
            import subprocess
            subprocess.run(
                ["wl-copy"], input=content, text=True, timeout=1,
            )
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

    def _get_flow_config(self):
        """Read flow config from config.json (cached, reloads on file change)."""
        try:
            from pathlib import Path
            cfg_path = Path.home() / ".config" / "juhradial" / "config.json"
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
        cfg = self._get_flow_config()
        remote_host = cfg.get("remote_host_index")
        if remote_host is None:
            logger.debug("No remote_host_index in flow config, skipping host switch")
            return
        self._dbus_set_host(int(remote_host))

    def _switch_host_to_linux(self):
        """Switch MX Master back to this Linux host via D-Bus Easy-Switch."""
        cfg = self._get_flow_config()
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
