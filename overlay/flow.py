"""
JuhRadialMX Flow - Multi-computer mouse/keyboard sharing

This module implements Flow functionality for seamlessly controlling multiple
computers with a single Logitech mouse. Inspired by and giving credit to:

- logitech-flow-kvm by Adam Coddington (coddingtonbear)
  https://github.com/coddingtonbear/logitech-flow-kvm
  Licensed under MIT License

The Flow protocol allows:
- Automatic device switching when moving between computers
- Clipboard synchronization between linked computers
- Secure pairing between computers on the same network
"""

import json
import os
import socket
import subprocess
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, List, Callable
from pathlib import Path

# For mDNS registration
try:
    from zeroconf import ServiceInfo, Zeroconf
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False

# Flow configuration
FLOW_PORT = 24801  # Same as logitech-flow-kvm for compatibility
LOGI_FLOW_PORT = 59866  # Official Logi Options+ Flow port
LOGI_DISCOVERY_PORT = 59867  # Logi Options+ UDP discovery port
FLOW_SERVICE_TYPE = "_juhradialmx._tcp.local."

# Data directory
DATA_DIR = Path.home() / ".local" / "share" / "juhradialmx"
TOKENS_FILE = DATA_DIR / "flow_tokens.json"
LINKED_COMPUTERS_FILE = DATA_DIR / "linked_computers.json"


def get_clipboard() -> str:
    """Get clipboard contents (supports Wayland and X11)"""
    try:
        # Try wl-paste first (Wayland)
        result = subprocess.run(
            ["wl-paste", "--no-newline"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        # Fall back to xclip (X11)
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return ""


def set_clipboard(content: str) -> bool:
    """Set clipboard contents (supports Wayland and X11)"""
    try:
        # Try wl-copy first (Wayland)
        result = subprocess.run(
            ["wl-copy"],
            input=content,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        # Fall back to xclip (X11)
        result = subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=content,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False


class FlowTokenManager:
    """Manages authentication tokens for Flow connections"""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.tokens: Dict[str, str] = {}
        self._load_tokens()

    def _load_tokens(self):
        """Load tokens from file"""
        if TOKENS_FILE.exists():
            try:
                with open(TOKENS_FILE, 'r', encoding='utf-8') as f:
                    self.tokens = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.tokens = {}

    def _save_tokens(self):
        """Save tokens to file"""
        with open(TOKENS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.tokens, f)

    def create_token(self, name: str) -> str:
        """Create a new authentication token"""
        token = str(uuid.uuid4())
        self.tokens[name] = token
        self._save_tokens()
        return token

    def verify_token(self, token: str) -> Optional[str]:
        """Verify a token and return the associated name"""
        for name, stored_token in self.tokens.items():
            if stored_token == token:
                return name
        return None

    def revoke_token(self, name: str) -> bool:
        """Revoke a token"""
        if name in self.tokens:
            del self.tokens[name]
            self._save_tokens()
            return True
        return False


class LinkedComputersManager:
    """Manages linked computers for Flow"""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.computers: Dict[str, dict] = {}
        self._load()

    def _load(self):
        """Load linked computers from file"""
        if LINKED_COMPUTERS_FILE.exists():
            try:
                with open(LINKED_COMPUTERS_FILE, 'r', encoding='utf-8') as f:
                    self.computers = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.computers = {}

    def _save(self):
        """Save linked computers to file"""
        with open(LINKED_COMPUTERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.computers, f, indent=2)

    def add_computer(self, name: str, ip: str, port: int, token: str) -> None:
        """Add a linked computer"""
        self.computers[name] = {
            'ip': ip,
            'port': port,
            'token': token,
            'linked_at': time.time()
        }
        self._save()

    def remove_computer(self, name: str) -> bool:
        """Remove a linked computer"""
        if name in self.computers:
            del self.computers[name]
            self._save()
            return True
        return False

    def get_all(self) -> Dict[str, dict]:
        """Get all linked computers"""
        return self.computers.copy()


class FlowRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Flow server"""

    server: 'FlowServer'

    def log_message(self, format, *args):
        """Override to use our logging"""
        print(f"[Flow Server] {args[0]}")

    def _get_auth_token(self) -> Optional[str]:
        """Extract Bearer token from Authorization header"""
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]
        return None

    def _verify_auth(self) -> Optional[str]:
        """Verify authentication and return client name if valid"""
        token = self._get_auth_token()
        if token:
            return self.server.token_manager.verify_token(token)
        return None

    def _send_json(self, data: dict, status: int = 200):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _send_text(self, text: str, status: int = 200):
        """Send text response"""
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(text.encode('utf-8'))

    def _send_error(self, status: int, message: str):
        """Send error response"""
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))

    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/info':
            # Public endpoint - server info
            self._send_json({
                'name': self.server.hostname,
                'version': '1.0',
                'software': 'JuhRadialMX',
                'host_slot': self.server.current_host_slot
            })
            return

        # All other endpoints require auth
        client_name = self._verify_auth()
        if not client_name:
            self._send_error(401, 'Unauthorized')
            return

        if self.path == '/status':
            self._send_json({
                'current_host': self.server.current_host_slot,
                'hostname': self.server.hostname
            })

        elif self.path == '/clipboard':
            clipboard_content = get_clipboard()
            self._send_text(clipboard_content)

        elif self.path == '/configuration':
            self._send_json({
                'hostname': self.server.hostname,
                'host_slot': self.server.current_host_slot
            })

        else:
            self._send_error(404, 'Not Found')

    # Maximum request body size (1MB) to prevent DoS attacks
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    def do_POST(self):
        """Handle POST requests"""
        content_length = int(self.headers.get('Content-Length', 0))

        # Prevent DoS via oversized requests
        if content_length > self.MAX_CONTENT_LENGTH:
            self._send_error(413, 'Request Entity Too Large')
            return

        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ''

        if self.path == '/pair':
            # Pairing request - no auth required
            try:
                data = json.loads(body)
                pairing_code = data.get('pairing_code', '')
                client_name = data.get('name', '')

                # Check if pairing code matches (set by user in UI)
                if self.server.pending_pairing_code and pairing_code == self.server.pending_pairing_code:
                    token = self.server.token_manager.create_token(client_name)
                    self.server.pending_pairing_code = None
                    self._send_json({'token': token, 'hostname': self.server.hostname})
                    print(f"[Flow] Paired with {client_name}")
                else:
                    self._send_error(401, 'Invalid pairing code')
            except json.JSONDecodeError:
                self._send_error(400, 'Invalid JSON')
            return

        # All other endpoints require auth
        client_name = self._verify_auth()
        if not client_name:
            self._send_error(401, 'Unauthorized')
            return

        if self.path == '/host_changed':
            # Another computer notified us that the host changed
            try:
                data = json.loads(body)
                new_host = data.get('host', 0)

                # Validate host slot (Easy-Switch supports 0-2 for 3 hosts)
                if not isinstance(new_host, int) or not 0 <= new_host <= 2:
                    self._send_error(400, f'Invalid host slot: must be 0-2')
                    return

                print(f"[Flow] Host change notification from {client_name}: switching to host {new_host}")

                # Switch our devices to the same host
                if self.server.on_host_change_callback:
                    self.server.on_host_change_callback(new_host)

                self._send_json({'status': 'ok'})
            except json.JSONDecodeError:
                self._send_error(400, 'Invalid JSON')

        elif self.path == '/clipboard':
            # Set clipboard
            set_clipboard(body)
            print(f"[Flow] Clipboard set from {client_name} ({len(body)} bytes)")
            self._send_json({'status': 'ok'})

        else:
            self._send_error(404, 'Not Found')

    def do_PUT(self):
        """Handle PUT requests (same as POST for clipboard)"""
        self.do_POST()

    def do_OPTIONS(self):
        """Handle OPTIONS for CORS preflight"""
        self.send_response(200)
        self.send_header('Allow', 'GET, POST, PUT, OPTIONS')
        self.end_headers()


class FlowServer(HTTPServer):
    """Flow server for JuhRadialMX"""

    def __init__(self, port: int = FLOW_PORT, on_host_change: Callable[[int], None] = None):
        self.hostname = socket.gethostname()
        self.current_host_slot = 0
        self.token_manager = FlowTokenManager()
        self.pending_pairing_code: Optional[str] = None
        self.on_host_change_callback = on_host_change
        self.zeroconf: Optional[Zeroconf] = None
        self.service_info: Optional[ServiceInfo] = None

        super().__init__(('0.0.0.0', port), FlowRequestHandler)
        print(f"[Flow] Server initialized on port {port}")

    def start(self):
        """Start the Flow server in a background thread"""
        # Register mDNS service
        self._register_mdns()

        # Start HTTP server in background thread
        self.server_thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.server_thread.start()
        print(f"[Flow] Server started at http://{self.hostname}:{self.server_address[1]}")

    def stop(self):
        """Stop the Flow server"""
        self._unregister_mdns()
        self.shutdown()

    def _register_mdns(self):
        """Register this computer on mDNS"""
        if not ZEROCONF_AVAILABLE:
            print("[Flow] Zeroconf not available, mDNS registration skipped")
            return

        try:
            self.zeroconf = Zeroconf()

            # Get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()

            self.service_info = ServiceInfo(
                FLOW_SERVICE_TYPE,
                f"{self.hostname}.{FLOW_SERVICE_TYPE}",
                addresses=[socket.inet_aton(local_ip)],
                port=self.server_address[1],
                properties={
                    'version': '1.0',
                    'hostname': self.hostname,
                    'software': 'JuhRadialMX'
                },
            )
            self.zeroconf.register_service(self.service_info)
            print(f"[Flow] Registered mDNS service: {self.hostname} at {local_ip}")
        except Exception as e:
            print(f"[Flow] Failed to register mDNS: {e}")

    def _unregister_mdns(self):
        """Unregister from mDNS"""
        if self.zeroconf and self.service_info:
            try:
                self.zeroconf.unregister_service(self.service_info)
                self.zeroconf.close()
            except Exception as e:
                print(f"[Flow] Error unregistering mDNS: {e}")

    def generate_pairing_code(self) -> str:
        """Generate a cryptographically secure pairing code for linking a new computer"""
        import secrets
        import string
        self.pending_pairing_code = ''.join(secrets.choice(string.digits) for _ in range(6))
        return self.pending_pairing_code

    def set_current_host(self, host_slot: int):
        """Update the current host slot"""
        self.current_host_slot = host_slot

    def notify_host_change(self, new_host: int, linked_computers: LinkedComputersManager):
        """Notify all linked computers of a host change"""
        import requests

        for name, computer in linked_computers.get_all().items():
            try:
                url = f"http://{computer['ip']}:{computer['port']}/host_changed"
                response = requests.post(
                    url,
                    json={'host': new_host},
                    headers={'Authorization': f"Bearer {computer['token']}"},
                    timeout=2
                )
                if response.ok:
                    print(f"[Flow] Notified {name} of host change to {new_host}")
                else:
                    print(f"[Flow] Failed to notify {name}: {response.status_code}")
            except Exception as e:
                print(f"[Flow] Error notifying {name}: {e}")

    def sync_clipboard_to(self, linked_computers: LinkedComputersManager):
        """Sync clipboard to all linked computers"""
        import requests

        clipboard_content = get_clipboard()
        if not clipboard_content:
            return

        for name, computer in linked_computers.get_all().items():
            try:
                url = f"http://{computer['ip']}:{computer['port']}/clipboard"
                response = requests.post(
                    url,
                    data=clipboard_content,
                    headers={'Authorization': f"Bearer {computer['token']}"},
                    timeout=2
                )
                if response.ok:
                    print(f"[Flow] Synced clipboard to {name}")
            except Exception as e:
                print(f"[Flow] Error syncing clipboard to {name}: {e}")


class LogiFlowDiscoveryResponder:
    """UDP responder for Logi Options+ Flow discovery

    Logi Options+ uses UDP broadcast on port 59867 to discover Flow-compatible
    computers on the network. This class listens for those broadcasts and responds
    so that Logi Options+ can find this computer.
    """

    def __init__(self, hostname: str = None):
        self.hostname = hostname or socket.gethostname()
        self.running = False
        self.sock = None
        self.thread = None

        # Get local IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self.local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            self.local_ip = "127.0.0.1"

    def start(self):
        """Start listening for discovery requests"""
        if self.running:
            return

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.sock.bind(('0.0.0.0', LOGI_DISCOVERY_PORT))
            self.sock.settimeout(1.0)

            self.running = True
            self.thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.thread.start()
            print(f"[Flow] Logi discovery responder started on UDP port {LOGI_DISCOVERY_PORT}")
        except Exception as e:
            print(f"[Flow] Failed to start Logi discovery responder: {e}")

    def stop(self):
        """Stop listening"""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

    def _listen_loop(self):
        """Main loop listening for discovery requests"""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                if data:
                    print(f"[Flow] Received discovery request from {addr}: {data[:50]}...")
                    self._send_response(addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[Flow] Discovery listener error: {e}")

    def _send_response(self, addr):
        """Send a discovery response"""
        try:
            # Create a response that Logi Options+ might recognize
            # This is experimental - the actual protocol is proprietary
            response = json.dumps({
                'hostname': self.hostname,
                'ip': self.local_ip,
                'port': LOGI_FLOW_PORT,
                'platform': 'linux',
                'software': 'JuhRadialMX',
                'flow_version': '1.0'
            }).encode('utf-8')

            self.sock.sendto(response, addr)
            print(f"[Flow] Sent discovery response to {addr}")
        except Exception as e:
            print(f"[Flow] Failed to send discovery response: {e}")


class LogiFlowServer:
    """HTTP server compatible with Logi Options+ Flow protocol

    Listens on port 59866 (official Logi Flow port) and attempts to respond
    to Logi Options+ requests.
    """

    def __init__(self):
        self.hostname = socket.gethostname()
        self.server = None
        self.thread = None

        # Get local IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self.local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            self.local_ip = "127.0.0.1"

    def start(self):
        """Start the Logi Flow compatible server"""
        try:
            self.server = HTTPServer(('0.0.0.0', LOGI_FLOW_PORT), LogiFlowRequestHandler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            print(f"[Flow] Logi Flow server started on port {LOGI_FLOW_PORT}")
        except Exception as e:
            print(f"[Flow] Failed to start Logi Flow server: {e}")

    def stop(self):
        """Stop the server"""
        if self.server:
            self.server.shutdown()


class LogiFlowRequestHandler(BaseHTTPRequestHandler):
    """Handle Logi Options+ Flow requests"""

    def log_message(self, format, *args):
        print(f"[LogiFlow] {args[0]}")

    def do_GET(self):
        """Handle GET requests from Logi Options+"""
        print(f"[LogiFlow] GET {self.path} from {self.client_address}")

        # Respond with computer info
        response = json.dumps({
            'hostname': socket.gethostname(),
            'platform': 'linux',
            'software': 'JuhRadialMX',
            'version': '1.0',
            'flow_enabled': True
        })

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

    def do_POST(self):
        """Handle POST requests from Logi Options+"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b''

        print(f"[LogiFlow] POST {self.path} from {self.client_address}: {body[:100]}")

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()


class FlowClient:
    """Client for connecting to another JuhRadialMX computer"""

    def __init__(self, server_ip: str, server_port: int = FLOW_PORT):
        self.server_ip = server_ip
        self.server_port = server_port
        self.token: Optional[str] = None

    def pair(self, pairing_code: str, my_name: str) -> bool:
        """Pair with the server using a pairing code"""
        import requests

        try:
            url = f"http://{self.server_ip}:{self.server_port}/pair"
            response = requests.post(
                url,
                json={'pairing_code': pairing_code, 'name': my_name},
                timeout=5
            )
            if response.ok:
                data = response.json()
                self.token = data.get('token')
                return True
        except Exception as e:
            print(f"[Flow Client] Pairing failed: {e}")
        return False

    def get_server_info(self) -> Optional[dict]:
        """Get server information"""
        import requests

        try:
            url = f"http://{self.server_ip}:{self.server_port}/info"
            response = requests.get(url, timeout=2)
            if response.ok:
                return response.json()
        except Exception as e:
            print(f"[Flow Client] Error getting server info: {e}")
        return None

    def notify_host_change(self, new_host: int) -> bool:
        """Notify the server of a host change"""
        import requests

        if not self.token:
            return False

        try:
            url = f"http://{self.server_ip}:{self.server_port}/host_changed"
            response = requests.post(
                url,
                json={'host': new_host},
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=2
            )
            return response.ok
        except Exception as e:
            print(f"[Flow Client] Error notifying host change: {e}")
        return False

    def sync_clipboard(self) -> bool:
        """Sync local clipboard to the server"""
        import requests

        if not self.token:
            return False

        clipboard_content = get_clipboard()
        if not clipboard_content:
            return True

        try:
            url = f"http://{self.server_ip}:{self.server_port}/clipboard"
            response = requests.post(
                url,
                data=clipboard_content,
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=2
            )
            return response.ok
        except Exception as e:
            print(f"[Flow Client] Error syncing clipboard: {e}")
        return False

    def get_clipboard(self) -> Optional[str]:
        """Get clipboard from the server"""
        import requests

        if not self.token:
            return None

        try:
            url = f"http://{self.server_ip}:{self.server_port}/clipboard"
            response = requests.get(
                url,
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=2
            )
            if response.ok:
                return response.text
        except Exception as e:
            print(f"[Flow Client] Error getting clipboard: {e}")
        return None


# Singleton instance for global access
_flow_server: Optional[FlowServer] = None
_linked_computers: Optional[LinkedComputersManager] = None
_logi_flow_server: Optional[LogiFlowServer] = None
_logi_discovery: Optional[LogiFlowDiscoveryResponder] = None


def get_flow_server() -> Optional[FlowServer]:
    """Get the global Flow server instance"""
    return _flow_server


def get_linked_computers() -> LinkedComputersManager:
    """Get the linked computers manager"""
    global _linked_computers
    if _linked_computers is None:
        _linked_computers = LinkedComputersManager()
    return _linked_computers


def start_flow_server(on_host_change: Callable[[int], None] = None) -> FlowServer:
    """Start the global Flow server and Logi Options+ compatibility layer"""
    global _flow_server, _logi_flow_server, _logi_discovery

    # Start main JuhRadialMX Flow server
    if _flow_server is None:
        _flow_server = FlowServer(on_host_change=on_host_change)
        _flow_server.start()

    # Start Logi Options+ compatible server on port 59866
    if _logi_flow_server is None:
        _logi_flow_server = LogiFlowServer()
        _logi_flow_server.start()

    # Start Logi Options+ UDP discovery responder
    if _logi_discovery is None:
        _logi_discovery = LogiFlowDiscoveryResponder()
        _logi_discovery.start()

    return _flow_server


def stop_flow_server():
    """Stop all Flow servers"""
    global _flow_server, _logi_flow_server, _logi_discovery

    if _flow_server:
        _flow_server.stop()
        _flow_server = None

    if _logi_flow_server:
        _logi_flow_server.stop()
        _logi_flow_server = None

    if _logi_discovery:
        _logi_discovery.stop()
        _logi_discovery = None
