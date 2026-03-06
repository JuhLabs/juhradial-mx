"""JuhRadialMX Flow - Multi-computer mouse/keyboard sharing

Inspired by logitech-flow-kvm by Adam Coddington (coddingtonbear)
https://github.com/coddingtonbear/logitech-flow-kvm (MIT License)

Sharded into:
  flow/constants.py       - Port numbers, paths, config
  flow/clipboard.py       - Wayland/X11 clipboard helpers
  flow/managers.py        - Token and linked computers persistence
  flow/server.py          - JuhRadialMX Flow HTTP server
  flow/client.py          - Flow client for connecting to peers
  flow/crypto.py          - X25519, HKDF, AESGCM wrapper + Logi packet format
  flow/keys.py            - Key generation, storage, peer key derivation
  flow/logi_discovery.py  - Logi Options+ UDP broadcast discovery (port 59870)
  flow/logi_presence.py   - Encrypted bidirectional TCP tunnel (port 59869)
  flow/logi_server.py     - Logi Options+ HTTP control server (port 59866)
  flow/edge_detector.py   - Screen edge cursor monitoring with dwell detection
  flow/handoff.py         - Cursor handoff orchestrator (edge -> encrypt -> warp)
"""

import logging
from typing import Optional, Callable

from .constants import FLOW_PORT
from .managers import FlowTokenManager, LinkedComputersManager
from .server import FlowServer
from .client import FlowClient
from .logi_discovery import LogiFlowDiscoveryResponder
from .logi_presence import FlowPresenceServer
from .logi_server import LogiFlowServer

logger = logging.getLogger("juhradial.flow")

# Singleton instances
_flow_server: Optional[FlowServer] = None
_linked_computers: Optional[LinkedComputersManager] = None
_logi_flow_server: Optional[LogiFlowServer] = None
_logi_discovery: Optional[LogiFlowDiscoveryResponder] = None
_presence_server: Optional['FlowPresenceServer'] = None
_handoff_manager = None
_edge_detector = None

# Crypto identity (set at startup)
_identity = None  # (private_key, public_key_bytes, node_id)


def get_flow_server() -> Optional[FlowServer]:
    return _flow_server


def get_linked_computers() -> LinkedComputersManager:
    global _linked_computers
    if _linked_computers is None:
        _linked_computers = LinkedComputersManager()
    return _linked_computers


def get_logi_discovery() -> Optional[LogiFlowDiscoveryResponder]:
    return _logi_discovery


def get_presence_server():
    return _presence_server


def get_handoff_manager():
    return _handoff_manager


def get_edge_detector():
    return _edge_detector


def _on_peer_key(peer_name: str, aes_key: bytes):
    """Callback when a new peer key is derived during pairing (server-side)."""
    if _logi_discovery:
        _logi_discovery.add_peer_key(peer_name, aes_key)
    if _presence_server:
        _presence_server.add_peer_key(peer_name, aes_key)


def start_flow_server(on_host_change: Callable[[int], None] = None) -> FlowServer:
    """Start the global Flow server and Logi Options+ compatibility layer"""
    global _flow_server, _logi_flow_server, _logi_discovery, _presence_server
    global _identity, _handoff_manager, _edge_detector

    # 1. Generate/load crypto identity
    from .keys import generate_identity, get_all_peers
    _identity = generate_identity()
    private_key, public_key_bytes, node_id = _identity

    # 2. Load existing peer AES keys
    peers = get_all_peers()

    # 3. Start JuhRadialMX Flow HTTP server
    if _flow_server is None:
        _flow_server = FlowServer(
            on_host_change=on_host_change,
            on_peer_key=_on_peer_key,
        )
        _flow_server.start()

    # 4. Start Logi HTTP compatibility server
    if _logi_flow_server is None:
        _logi_flow_server = LogiFlowServer()
        _logi_flow_server.start()

    # 5. Start encrypted presence server with peer keys
    if _presence_server is None:
        _presence_server = FlowPresenceServer(
            node_id=node_id,
            peer_aes_keys={name: p["aes_key_bytes"] for name, p in peers.items()},
        )
        _presence_server.start()

    # 6. Start encrypted discovery with identity and peer keys
    if _logi_discovery is None:
        _logi_discovery = LogiFlowDiscoveryResponder(
            node_id=node_id,
            private_key=private_key,
            public_key_bytes=public_key_bytes,
        )
        for name, peer in peers.items():
            _logi_discovery.add_peer_key(name, peer["aes_key_bytes"])
        _logi_discovery.start()

    # 7. Start edge detector and handoff manager
    try:
        from .edge_detector import ScreenEdgeDetector
        from .handoff import FlowHandoffManager

        if _edge_detector is None:
            _edge_detector = ScreenEdgeDetector()

        if _handoff_manager is None:
            _handoff_manager = FlowHandoffManager(
                edge_detector=_edge_detector,
                presence_server=_presence_server,
            )
            # Connect outgoing presence clients to known peers
            for name, peer in peers.items():
                _handoff_manager.connect_to_peer(
                    name, peer["ip"], peer.get("port", FLOW_PORT),
                    node_id, peer["aes_key_bytes"],
                )

        # Start edge detector if edge trigger is enabled
        # (settings UI will call edge_detector.set_enabled() based on config)
        _edge_detector.start()
    except Exception as e:
        logger.warning("Edge detector/handoff setup deferred: %s", e)

    return _flow_server


def stop_flow_server():
    """Stop all Flow servers"""
    global _flow_server, _logi_flow_server, _logi_discovery, _presence_server
    global _handoff_manager, _edge_detector

    if _edge_detector:
        _edge_detector.stop()
        _edge_detector = None

    if _handoff_manager:
        _handoff_manager.stop()
        _handoff_manager = None

    if _flow_server:
        _flow_server.stop()
        _flow_server = None

    if _logi_flow_server:
        _logi_flow_server.stop()
        _logi_flow_server = None

    if _presence_server:
        _presence_server.stop()
        _presence_server = None

    if _logi_discovery:
        _logi_discovery.stop()
        _logi_discovery = None
