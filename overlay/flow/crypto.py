"""
Cryptographic primitives for Flow encrypted communication.

Uses X25519 key exchange, HKDF-SHA256 key derivation, and AES-256-GCM
encryption - matching the Logi Options+ Flow protocol for interop
compatibility.
"""

import hashlib
import logging
import os
import struct

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .constants import (
    FLOW_HKDF_INFO,
    FLOW_NONCE_LEN,
    FLOW_PROTOCOL_VERSION,
    FLOW_TAG_LEN,
)

logger = logging.getLogger("juhradial.flow.crypto")


def generate_x25519_keypair():
    """Generate X25519 private key, return (private_key, public_key_bytes_32)."""
    private_key = X25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes_raw()
    return private_key, public_bytes


def derive_shared_secret(our_private, their_public_bytes):
    """X25519 ECDH -> 32-byte shared secret."""
    their_public = X25519PublicKey.from_public_bytes(their_public_bytes)
    return our_private.exchange(their_public)


def derive_aes_key(shared_secret, salt=None, info=FLOW_HKDF_INFO):
    """HKDF-SHA256 -> 32-byte AES key from shared secret."""
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        info=info,
    )
    return hkdf.derive(shared_secret)


def generate_node_id(machine_id=None):
    """SHA-256 hash of /etc/machine-id -> 32 bytes."""
    if machine_id is None:
        try:
            machine_id = open("/etc/machine-id").read().strip()
        except OSError:
            logger.warning("Cannot read /etc/machine-id, generating random node ID")
            return os.urandom(32)
    return hashlib.sha256(machine_id.encode()).digest()


def encrypt_payload(aes_key, plaintext):
    """
    AES-256-GCM encrypt.
    Returns (nonce_12B, tag_16B, ciphertext).
    Python cryptography appends tag to ciphertext, so we split.
    """
    nonce = os.urandom(FLOW_NONCE_LEN)
    aesgcm = AESGCM(aes_key)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext, None)
    ciphertext = ct_with_tag[:-FLOW_TAG_LEN]
    tag = ct_with_tag[-FLOW_TAG_LEN:]
    return nonce, tag, ciphertext


def decrypt_payload(aes_key, nonce, tag, ciphertext):
    """Reconstruct ciphertext + tag, then decrypt."""
    aesgcm = AESGCM(aes_key)
    ct_with_tag = ciphertext + tag
    return aesgcm.decrypt(nonce, ct_with_tag, None)


def build_encrypted_packet(node_id, aes_key, plaintext):
    """
    Assemble Logi-format encrypted packet:
      [0:32]  node_id
      [32:34] version (BE u16)
      [34:36] payload_len (BE u16)
      [36:38] nonce_len = 0x000C (BE u16)
      [38:40] reserved = 0x0000 (BE u16)
      [40:42] ct_len (BE u16)
      [42:44] tag_len = 0x0010 (BE u16)
      [44:56] nonce (12 bytes)
      [56:72] tag (16 bytes)
      [72:end] ciphertext
    """
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")

    nonce, tag, ciphertext = encrypt_payload(aes_key, plaintext)
    ct_len = len(ciphertext)
    payload_len = FLOW_NONCE_LEN + FLOW_TAG_LEN + ct_len

    header = struct.pack(
        ">32s HH HH HH",
        node_id,
        FLOW_PROTOCOL_VERSION,
        payload_len,
        FLOW_NONCE_LEN,
        0x0000,  # reserved
        ct_len,
        FLOW_TAG_LEN,
    )
    return header + nonce + tag + ciphertext


def parse_encrypted_packet(data):
    """
    Parse Logi-format encrypted packet.
    Returns (node_id, nonce, tag, ciphertext) or None on failure.
    """
    if len(data) < 72:
        return None

    try:
        node_id = data[0:32]
        version = struct.unpack(">H", data[32:34])[0]
        payload_len = struct.unpack(">H", data[34:36])[0]
        nonce_len = struct.unpack(">H", data[36:38])[0]
        # reserved = data[38:40]
        ct_len = struct.unpack(">H", data[40:42])[0]
        tag_len = struct.unpack(">H", data[42:44])[0]

        if version != FLOW_PROTOCOL_VERSION:
            logger.debug("Unknown protocol version: 0x%04x", version)
            return None

        if nonce_len != FLOW_NONCE_LEN or tag_len != FLOW_TAG_LEN:
            logger.debug("Unexpected nonce/tag len: %d/%d", nonce_len, tag_len)
            return None

        expected_total = 44 + nonce_len + tag_len + ct_len
        if len(data) < expected_total:
            logger.debug("Packet too short: %d < %d", len(data), expected_total)
            return None

        nonce = data[44:44 + nonce_len]
        tag = data[44 + nonce_len:44 + nonce_len + tag_len]
        ciphertext = data[44 + nonce_len + tag_len:44 + nonce_len + tag_len + ct_len]

        return node_id, nonce, tag, ciphertext
    except (struct.error, IndexError) as e:
        logger.debug("Failed to parse encrypted packet: %s", e)
        return None
