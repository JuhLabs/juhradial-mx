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
