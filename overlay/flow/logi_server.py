"""Logi Options+ HTTP server on port 59866 (secure peer control channel)

Includes verbose logging for protocol reverse-engineering.
"""

import json
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from flow.constants import LOGI_FLOW_PORT


class _ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


class LogiFlowRequestHandler(BaseHTTPRequestHandler):
    """Handle Logi Options+ Flow requests on port 59866

    Verbose logging of all headers, body, and source IP.
    """

    def log_message(self, format, *args):
        print(f"[LogiFlow 59866] {args[0]}")

    def _log_request_details(self, method: str):
        print(f"\n[LogiFlow 59866] === {method} REQUEST ===")
        print(f"[LogiFlow 59866] Path: {self.path}")
        print(f"[LogiFlow 59866] From: {self.client_address[0]}:{self.client_address[1]}")
        print(f"[LogiFlow 59866] Headers:")
        for header, value in self.headers.items():
            print(f"[LogiFlow 59866]   {header}: {value}")

    def do_GET(self):
        self._log_request_details("GET")
        print(f"[LogiFlow 59866] === END REQUEST ===\n")

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
        self._log_request_details("POST")

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b''

        print(f"[LogiFlow 59866] Body ({len(body)} bytes):")
        for i in range(0, min(len(body), 256), 16):
            chunk = body[i:i+16]
            hex_part = ' '.join(f'{b:02x}' for b in chunk)
            ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            print(f"[LogiFlow 59866]   {i:04x}: {hex_part:<48s}  {ascii_part}")
        if len(body) > 256:
            print(f"[LogiFlow 59866]   ... ({len(body) - 256} more bytes)")
        try:
            print(f"[LogiFlow 59866] Body UTF-8: {body.decode('utf-8')[:500]}")
        except UnicodeDecodeError:
            pass
        print(f"[LogiFlow 59866] === END REQUEST ===\n")

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def do_PUT(self):
        self.do_POST()

    def do_OPTIONS(self):
        self._log_request_details("OPTIONS")
        print(f"[LogiFlow 59866] === END REQUEST ===\n")
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()


class LogiFlowServer:
    """HTTP server compatible with Logi Options+ Flow protocol"""

    def __init__(self):
        self.hostname = socket.gethostname()
        self.server = None
        self.thread = None

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self.local_ip = s.getsockname()[0]
            s.close()
        except OSError:
            self.local_ip = "127.0.0.1"

    def start(self):
        try:
            self.server = _ReusableHTTPServer(('', LOGI_FLOW_PORT), LogiFlowRequestHandler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            print(f"[Flow] Logi Flow server on TCP port {LOGI_FLOW_PORT}")
        except Exception as e:
            print(f"[Flow] Failed to start Logi Flow server: {e}")

    def stop(self):
        if self.server:
            self.server.shutdown()
