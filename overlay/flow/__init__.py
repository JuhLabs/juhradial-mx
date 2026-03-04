"""JuhRadialMX Flow - Multi-computer mouse/keyboard sharing

Inspired by logitech-flow-kvm by Adam Coddington (coddingtonbear)
https://github.com/coddingtonbear/logitech-flow-kvm (MIT License)

Sharded into:
  flow/constants.py       - Port numbers, paths, config
  flow/clipboard.py       - Wayland/X11 clipboard helpers
  flow/managers.py        - Token and linked computers persistence
  flow/server.py          - JuhRadialMX Flow HTTP server
  flow/client.py          - Flow client for connecting to peers
  flow/logi_discovery.py  - Logi Options+ UDP broadcast discovery (port 59870)
  flow/logi_presence.py   - Logi Options+ TCP presence server (port 59869)
  flow/logi_server.py     - Logi Options+ HTTP control server (port 59866)
"""

from typing import Optional, Callable

from flow.constants import FLOW_PORT
from flow.managers import FlowTokenManager, LinkedComputersManager
from flow.server import FlowServer
from flow.client import FlowClient
from flow.logi_discovery import LogiFlowDiscoveryResponder
from flow.logi_presence import LogiFlowPresenceServer
from flow.logi_server import LogiFlowServer

# Singleton instances
_flow_server: Optional[FlowServer] = None
_linked_computers: Optional[LinkedComputersManager] = None
_logi_flow_server: Optional[LogiFlowServer] = None
_logi_discovery: Optional[LogiFlowDiscoveryResponder] = None
_logi_presence: Optional[LogiFlowPresenceServer] = None


def get_flow_server() -> Optional[FlowServer]:
    return _flow_server


def get_linked_computers() -> LinkedComputersManager:
    global _linked_computers
    if _linked_computers is None:
        _linked_computers = LinkedComputersManager()
    return _linked_computers


def get_logi_discovery() -> Optional[LogiFlowDiscoveryResponder]:
    return _logi_discovery


def start_flow_server(on_host_change: Callable[[int], None] = None) -> FlowServer:
    """Start the global Flow server and Logi Options+ compatibility layer"""
    global _flow_server, _logi_flow_server, _logi_discovery, _logi_presence

    if _flow_server is None:
        _flow_server = FlowServer(on_host_change=on_host_change)
        _flow_server.start()

    if _logi_flow_server is None:
        _logi_flow_server = LogiFlowServer()
        _logi_flow_server.start()

    if _logi_presence is None:
        _logi_presence = LogiFlowPresenceServer()
        _logi_presence.start()

    if _logi_discovery is None:
        _logi_discovery = LogiFlowDiscoveryResponder()
        _logi_discovery.start()

    return _flow_server


def stop_flow_server():
    """Stop all Flow servers"""
    global _flow_server, _logi_flow_server, _logi_discovery, _logi_presence

    if _flow_server:
        _flow_server.stop()
        _flow_server = None

    if _logi_flow_server:
        _logi_flow_server.stop()
        _logi_flow_server = None

    if _logi_presence:
        _logi_presence.stop()
        _logi_presence = None

    if _logi_discovery:
        _logi_discovery.stop()
        _logi_discovery = None
