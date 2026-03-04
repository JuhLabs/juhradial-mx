"""JuhRadialMX Flow HTTP server and request handler"""

import json
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Callable

try:
    from zeroconf import ServiceInfo, Zeroconf
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False

from flow.constants import FLOW_PORT, FLOW_SERVICE_TYPE
from flow.clipboard import get_clipboard, set_clipboard
from flow.managers import FlowTokenManager, LinkedComputersManager


class FlowRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Flow server"""

    server: 'FlowServer'

    def log_message(self, format, *args):
        print(f"[Flow Server] {args[0]}")

    def _get_auth_token(self) -> Optional[str]:
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]
        return None

    def _verify_auth(self) -> Optional[str]:
        token = self._get_auth_token()
        if token:
            return self.server.token_manager.verify_token(token)
        return None

    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _send_text(self, text: str, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(text.encode('utf-8'))

    def _send_error(self, status: int, message: str):
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))

    def do_GET(self):
        if self.path == '/info':
            self._send_json({
                'name': self.server.hostname,
                'version': '1.0',
                'software': 'JuhRadialMX',
                'host_slot': self.server.current_host_slot
            })
            return

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
            self._send_text(get_clipboard())
        elif self.path == '/configuration':
            self._send_json({
                'hostname': self.server.hostname,
                'host_slot': self.server.current_host_slot
            })
        else:
            self._send_error(404, 'Not Found')

    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))

        if content_length > self.MAX_CONTENT_LENGTH:
            self._send_error(413, 'Request Entity Too Large')
            return

        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ''

        if self.path == '/pair':
            try:
                data = json.loads(body)
                pairing_code = data.get('pairing_code', '')
                client_name = data.get('name', '')

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

        client_name = self._verify_auth()
        if not client_name:
            self._send_error(401, 'Unauthorized')
            return

        if self.path == '/host_changed':
            try:
                data = json.loads(body)
                new_host = data.get('host', 0)

                if not isinstance(new_host, int) or not 0 <= new_host <= 2:
                    self._send_error(400, 'Invalid host slot: must be 0-2')
                    return

                print(f"[Flow] Host change from {client_name}: host {new_host}")
                if self.server.on_host_change_callback:
                    self.server.on_host_change_callback(new_host)
                self._send_json({'status': 'ok'})
            except json.JSONDecodeError:
                self._send_error(400, 'Invalid JSON')

        elif self.path == '/clipboard':
            set_clipboard(body)
            print(f"[Flow] Clipboard set from {client_name} ({len(body)} bytes)")
            self._send_json({'status': 'ok'})
        else:
            self._send_error(404, 'Not Found')

    def do_PUT(self):
        self.do_POST()

    def do_OPTIONS(self):
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
        self.zeroconf: Optional['Zeroconf'] = None
        self.service_info: Optional['ServiceInfo'] = None

        self.allow_reuse_address = True
        super().__init__(('', port), FlowRequestHandler)
        print(f"[Flow] Server initialized on port {port}")

    def start(self):
        self._register_mdns()
        self.server_thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.server_thread.start()
        print(f"[Flow] Server started at http://{self.hostname}:{self.server_address[1]}")

    def stop(self):
        self._unregister_mdns()
        self.shutdown()

    def _register_mdns(self):
        if not ZEROCONF_AVAILABLE:
            print("[Flow] Zeroconf not available, mDNS registration skipped")
            return

        try:
            self.zeroconf = Zeroconf()
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
        if self.zeroconf and self.service_info:
            try:
                self.zeroconf.unregister_service(self.service_info)
                self.zeroconf.close()
            except Exception as e:
                print(f"[Flow] Error unregistering mDNS: {e}")

    def generate_pairing_code(self) -> str:
        import secrets
        import string
        self.pending_pairing_code = ''.join(secrets.choice(string.digits) for _ in range(6))
        return self.pending_pairing_code

    def set_current_host(self, host_slot: int):
        self.current_host_slot = host_slot

    def notify_host_change(self, new_host: int, linked_computers: LinkedComputersManager):
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
