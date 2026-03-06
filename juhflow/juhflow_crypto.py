"""Crypto module for JuhFlow Mac app.

Mirrors overlay/flow/crypto.py from the Linux side.
Implements X25519 key exchange, HKDF-SHA256, and AES-256-GCM
for the encrypted bridge between JuhFlow (Mac) and JuhRadial MX (Linux).
"""

import hashlib
import os
import struct

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Protocol constants (must match Linux side)
PROTOCOL_VERSION = 0x0000
HKDF_INFO = b"juhradial-flow-v1"
NONCE_LEN = 12
TAG_LEN = 16


def generate_keypair():
    """Generate X25519 keypair. Returns (private_key, public_key_bytes_32)."""
    private_key = X25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes_raw()
    return private_key, public_bytes


def derive_shared_secret(our_private, their_public_bytes):
    """X25519 ECDH -> 32-byte shared secret."""
    their_public = X25519PublicKey.from_public_bytes(their_public_bytes)
    return our_private.exchange(their_public)


def derive_aes_key(shared_secret, salt=None):
    """HKDF-SHA256 -> 32-byte AES key from shared secret."""
    hkdf = HKDF(algorithm=SHA256(), length=32, salt=salt, info=HKDF_INFO)
    return hkdf.derive(shared_secret)


def generate_node_id():
    """Generate node ID from macOS hardware UUID or random."""
    try:
        import subprocess
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "IOPlatformUUID" in line:
                uuid = line.split('"')[-2]
                return hashlib.sha256(uuid.encode()).digest()
    except Exception:
        pass
    return os.urandom(32)


def encrypt_payload(aes_key, plaintext):
    """AES-256-GCM encrypt. Returns (nonce, tag, ciphertext)."""
    nonce = os.urandom(NONCE_LEN)
    aesgcm = AESGCM(aes_key)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext, None)
    return nonce, ct_with_tag[-TAG_LEN:], ct_with_tag[:-TAG_LEN]


def decrypt_payload(aes_key, nonce, tag, ciphertext):
    """Decrypt AES-256-GCM. Returns plaintext."""
    aesgcm = AESGCM(aes_key)
    return aesgcm.decrypt(nonce, ciphertext + tag, None)


def build_encrypted_packet(node_id, aes_key, plaintext):
    """Build Logi-format encrypted packet (matches Linux crypto.py)."""
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    nonce, tag, ciphertext = encrypt_payload(aes_key, plaintext)
    ct_len = len(ciphertext)
    payload_len = NONCE_LEN + TAG_LEN + ct_len
    header = struct.pack(
        ">32s HH HH HH",
        node_id, PROTOCOL_VERSION, payload_len,
        NONCE_LEN, 0x0000, ct_len, TAG_LEN,
    )
    return header + nonce + tag + ciphertext


def parse_encrypted_packet(data):
    """Parse Logi-format encrypted packet. Returns (node_id, nonce, tag, ct) or None."""
    if len(data) < 72:
        return None
    try:
        node_id = data[0:32]
        nonce_len = struct.unpack(">H", data[36:38])[0]
        ct_len = struct.unpack(">H", data[40:42])[0]
        tag_len = struct.unpack(">H", data[42:44])[0]
        nonce = data[44:44 + nonce_len]
        tag = data[44 + nonce_len:44 + nonce_len + tag_len]
        ciphertext = data[44 + nonce_len + tag_len:44 + nonce_len + tag_len + ct_len]
        return node_id, nonce, tag, ciphertext
    except (struct.error, IndexError):
        return None
