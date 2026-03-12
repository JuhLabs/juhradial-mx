"""Logi Options+ HTTP server on port 59866 (secure peer control channel)"""

import json
import logging
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from .constants import LOGI_FLOW_PORT

logger = logging.getLogger("juhradial.flow.logi_server")

# Maximum request body size (64 KB - sufficient for JSON control messages)
MAX_CONTENT_LENGTH = 65_536


class _ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


class LogiFlowRequestHandler(BaseHTTPRequestHandler):
    """Handle Logi Options+ Flow requests on port 59866"""

    def log_message(self, format, *args):
        logger.debug("HTTP %s", args[0])

    def do_GET(self):
        logger.debug("GET %s from %s", self.path, self.client_address[0])

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
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > MAX_CONTENT_LENGTH:
            logger.warning("Request body too large: %d bytes from %s",
                           content_length, self.client_address[0])
            self.send_response(413)
            self.end_headers()
            return

        body = self.rfile.read(content_length) if content_length > 0 else b''
        logger.debug("POST %s from %s (%d bytes)",
                      self.path, self.client_address[0], len(body))

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def do_PUT(self):
        self.do_POST()

    def do_OPTIONS(self):
        logger.debug("OPTIONS %s from %s", self.path, self.client_address[0])
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
            logger.info("Logi Flow server on TCP port %d", LOGI_FLOW_PORT)
        except Exception as e:
            logger.error("Failed to start Logi Flow server: %s", e)

    def stop(self):
        if self.server:
            self.server.shutdown()
