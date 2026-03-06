"""Flow protocol constants and configuration"""

from pathlib import Path

# JuhRadialMX Flow server port (logitech-flow-kvm compatible)
FLOW_PORT = 24801

# Official Logi Options+ Flow ports
LOGI_FLOW_PORT = 59866      # Secure peer control channel (TCP)
LOGI_PRESENCE_PORT = 59869   # Presence connection (TCP, default, customizable)
LOGI_DISCOVERY_PORT = 59870  # Broadcast discovery (UDP, FIXED)
LOGI_NODESTORE_PORT = 59871  # NodeStore ping/pong discovery (UDP)

# mDNS service type for JuhRadialMX-to-JuhRadialMX discovery
FLOW_SERVICE_TYPE = "_juhradialmx._tcp.local."

# Discovery broadcast interval in seconds
DISCOVERY_BROADCAST_INTERVAL = 5

# Data directory
DATA_DIR = Path.home() / ".local" / "share" / "juhradialmx"
TOKENS_FILE = DATA_DIR / "flow_tokens.json"
LINKED_COMPUTERS_FILE = DATA_DIR / "linked_computers.json"

# Crypto key storage
FLOW_KEYS_DIR = Path.home() / ".config" / "juhradial" / "flow_keys"
FLOW_PEERS_DIR = FLOW_KEYS_DIR / "peers"

# Encrypted protocol constants
FLOW_PROTOCOL_VERSION = 0x0000
FLOW_HKDF_INFO = b"juhradial-flow-v1"
FLOW_NONCE_LEN = 12
FLOW_TAG_LEN = 16

# Screen edge detection
EDGE_THRESHOLD_PX = 2
EDGE_DWELL_MS = 300
EDGE_POLL_INTERVAL_MS = 16
EDGE_COOLDOWN_MS = 1000

# Message types for encrypted presence channel
MSG_DISCOVERY_BEACON = "discovery_beacon"
MSG_CURSOR_HANDOFF = "cursor_handoff"
MSG_CLIPBOARD_SYNC = "clipboard_sync"
MSG_HEARTBEAT = "heartbeat"
