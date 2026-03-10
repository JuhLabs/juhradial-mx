"""
Key lifecycle management for Flow encrypted communication.

Handles X25519 keypair generation, storage, and peer key derivation.
Keys stored in ~/.config/juhradial/flow_keys/ (mode 0o700).
"""

import json
import logging
import os

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .constants import FLOW_KEYS_DIR, FLOW_PEERS_DIR
from .crypto import derive_aes_key, derive_shared_secret, generate_node_id

logger = logging.getLogger("juhradial.flow.keys")


def _sanitize_log(value) -> str:
    """Strip newlines and control characters to prevent log injection."""
    return ''.join(c if c >= ' ' and c != '\x7f' else '?' for c in str(value))


def get_keys_dir():
    """Return/create keys directory with restricted permissions."""
    FLOW_KEYS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(FLOW_KEYS_DIR, 0o700)
    return FLOW_KEYS_DIR


def generate_identity():
    """
    Load or generate X25519 keypair + node_id from /etc/machine-id.
    Returns (private_key, public_key_bytes, node_id).
    """
    keys_dir = get_keys_dir()
    priv_path = keys_dir / "private.key"
    pub_path = keys_dir / "public.key"
    nid_path = keys_dir / "node_id.bin"

    if priv_path.exists() and pub_path.exists() and nid_path.exists():
        try:
            priv_raw = priv_path.read_bytes()
            private_key = X25519PrivateKey.from_private_bytes(priv_raw)
            public_bytes = pub_path.read_bytes()
            node_id = nid_path.read_bytes()
            logger.info("Loaded existing Flow identity")
            return private_key, public_bytes, node_id
        except Exception as e:
            logger.warning("Failed to load keys, regenerating: %s", e)

    from .crypto import generate_x25519_keypair
    private_key, public_bytes = generate_x25519_keypair()
    node_id = generate_node_id()

    priv_path.write_bytes(private_key.private_bytes_raw())
    os.chmod(priv_path, 0o600)
    pub_path.write_bytes(public_bytes)
    nid_path.write_bytes(node_id)

    logger.info("Generated new Flow identity (pubkey: %s...)", public_bytes.hex()[:16])
    return private_key, public_bytes, node_id


def get_public_key_hex():
    """Hex string of our public key (for UI display + pairing)."""
    keys_dir = get_keys_dir()
    pub_path = keys_dir / "public.key"
    if pub_path.exists():
        return pub_path.read_bytes().hex()
    _, pub_bytes, _ = generate_identity()
    return pub_bytes.hex()


def get_node_id():
    """Read cached node_id or regenerate."""
    keys_dir = get_keys_dir()
    nid_path = keys_dir / "node_id.bin"
    if nid_path.exists():
        return nid_path.read_bytes()
    _, _, node_id = generate_identity()
    return node_id


def derive_and_store_peer_key(peer_name, peer_pubkey_hex, ip, port):
    """
    Full pipeline: load private key, derive shared secret, HKDF, save peer.
    Returns the derived AES key.
    """
    keys_dir = get_keys_dir()
    priv_path = keys_dir / "private.key"
    priv_raw = priv_path.read_bytes()
    if len(priv_raw) != 32:
        raise ValueError(f"Invalid private key size: {len(priv_raw)} bytes (expected 32)")
    private_key = X25519PrivateKey.from_private_bytes(priv_raw)

    if len(peer_pubkey_hex) != 64:
        raise ValueError(f"Invalid peer public key hex length: {len(peer_pubkey_hex)} (expected 64)")
    peer_pubkey_bytes = bytes.fromhex(peer_pubkey_hex)
    shared_secret = derive_shared_secret(private_key, peer_pubkey_bytes)
    aes_key = derive_aes_key(shared_secret)

    FLOW_PEERS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(FLOW_PEERS_DIR, 0o700)
    peer_file = FLOW_PEERS_DIR / f"{peer_name}.json"
    peer_data = {
        "name": peer_name,
        "public_key": peer_pubkey_hex,
        "ip": ip,
        "port": port,
        "aes_key": aes_key.hex(),
    }
    peer_file.write_text(json.dumps(peer_data, indent=2))
    os.chmod(peer_file, 0o600)
    logger.info("Stored peer key for %s (%s)", _sanitize_log(peer_name), _sanitize_log(ip))
    return aes_key


def load_peer_key(peer_name):
    """Load a peer's AES key and info. Returns dict or None."""
    peer_file = FLOW_PEERS_DIR / f"{peer_name}.json"
    if not peer_file.exists():
        return None
    try:
        data = json.loads(peer_file.read_text())
        data["aes_key_bytes"] = bytes.fromhex(data["aes_key"])
        return data
    except Exception as e:
        logger.warning("Failed to load peer key for %s: %s", peer_name, e)
        return None


def get_all_peers():
    """Load all peer keys. Returns dict of {name: peer_data}."""
    if not FLOW_PEERS_DIR.exists():
        return {}
    peers = {}
    for peer_file in FLOW_PEERS_DIR.glob("*.json"):
        try:
            data = json.loads(peer_file.read_text())
            data["aes_key_bytes"] = bytes.fromhex(data["aes_key"])
            peers[data["name"]] = data
        except Exception as e:
            logger.warning("Failed to load peer %s: %s", peer_file.name, e)
    return peers


def delete_peer_key(peer_name):
    """Delete a peer's key file. Returns True if deleted."""
    peer_file = FLOW_PEERS_DIR / f"{peer_name}.json"
    if peer_file.exists():
        peer_file.unlink()
        logger.info("Deleted peer key for %s", peer_name)
        return True
    return False
