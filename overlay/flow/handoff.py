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
    FLOW_PORT,
    LOGI_PRESENCE_PORT,
    MSG_CURSOR_HANDOFF,
    MSG_CLIPBOARD_SYNC,
    EDGE_COOLDOWN_MS,
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

    Connects: edge detector -> presence clients -> cursor warp
    """

    def __init__(self, edge_detector=None, presence_server=None):
        self.edge_detector = edge_detector
        self.presence_server = presence_server

        # {peer_name: FlowPresenceClient}
        self.presence_clients: Dict[str, 'FlowPresenceClient'] = {}
        self._clients_lock = threading.Lock()

        # {peer_name: edge} - which edge each peer is assigned to
        self.peer_edges: Dict[str, str] = {}

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
        position, and sends cursor_handoff + clipboard_sync.
        """
        # Find peer for this edge
        peer_name = None
        for name, peer_edge in self.peer_edges.items():
            if peer_edge == edge:
                peer_name = name
                break

        if not peer_name:
            logger.debug("No peer configured for %s edge", edge)
            return

        # Compute relative position along the edge (0.0 - 1.0)
        sx, sy = screen["x"], screen["y"]
        sw, sh = screen["width"], screen["height"]

        if edge in ("left", "right"):
            relative_pos = (cy - sy) / sh if sh > 0 else 0.5
        else:
            relative_pos = (cx - sx) / sw if sw > 0 else 0.5

        relative_pos = max(0.0, min(1.0, relative_pos))

        # Send cursor handoff message
        handoff_msg = {
            "type": MSG_CURSOR_HANDOFF,
            "edge": edge,
            "relative_position": relative_pos,
            "screen_width": sw,
            "screen_height": sh,
        }

        sent = self._send_to_peer(peer_name, handoff_msg)
        if sent:
            logger.info("Cursor handoff to %s via %s edge (rel: %.2f)", peer_name, edge, relative_pos)

            # Also send clipboard content
            try:
                import subprocess
                result = subprocess.run(
                    ["wl-paste", "--no-newline"],
                    capture_output=True, text=True, timeout=1,
                )
                clipboard_content = result.stdout if result.returncode == 0 else ""
                if clipboard_content:
                    clipboard_msg = {
                        "type": MSG_CLIPBOARD_SYNC,
                        "content": clipboard_content,
                    }
                    self._send_to_peer(peer_name, clipboard_msg)
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
        from overlay.overlay_cursor import get_screen_geometry, warp_cursor
        screen = get_screen_geometry()
        sx, sy = screen["x"], screen["y"]
        sw, sh = screen["width"], screen["height"]

        # Compute arrival position on opposite edge
        if arrival_edge == "left":
            x = sx + 5  # slightly inside the edge
            y = sy + int(relative_pos * sh)
        elif arrival_edge == "right":
            x = sx + sw - 5
            y = sy + int(relative_pos * sh)
        elif arrival_edge == "top":
            x = sx + int(relative_pos * sw)
            y = sy + 5
        elif arrival_edge == "bottom":
            x = sx + int(relative_pos * sw)
            y = sy + sh - 5
        else:
            x = sx + sw // 2
            y = sy + sh // 2

        # Suppress edge detector to prevent immediate bounce-back
        if self.edge_detector:
            self.edge_detector.suppress_for(EDGE_COOLDOWN_MS)

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
