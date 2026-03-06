"""thekogans Marconi wire format implementation.

Implements the binary protocol used by Logi Options+ Flow for P2P
encrypted communication. Based on reverse engineering of
logioptionsplus_agent v1.99.834046 and thekogans open-source libraries.

Wire format layers:
  FrameHeader (36B) -> CiphertextBlock -> PlaintextHeader -> SerializableHeader -> Packet

References:
  - https://github.com/thekogans/packet (FrameParser, Packet, Session)
  - https://github.com/thekogans/crypto (Cipher, KeyExchange, SymmetricKey)
  - https://github.com/thekogans/util  (Serializable, SizeT)
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

logger = logging.getLogger("juhradial.flow.marconi")

# AES-256-GCM constants
GCM_IV_LEN = 12
GCM_TAG_LEN = 16
GCM_KEY_LEN = 32

# PlaintextHeader flags
FLAGS_SESSION_HEADER = 0x01
FLAGS_COMPRESSED = 0x02

# Session header size (GUID 16B + inbound seq 4B + outbound seq 4B = 24B)
SESSION_HEADER_SIZE = 24

# Maximum random padding in PlaintextHeader
MAX_RANDOM_LENGTH = 100

# Frame header size: keyId (32B) + ciphertextLength (4B)
FRAME_HEADER_SIZE = 36


# ---------------------------------------------------------------------------
# SizeT: thekogans variable-length integer encoding
# ---------------------------------------------------------------------------

def sizet_encode(value):
    """Encode a value using thekogans SizeT prefix-varint format.

    Encoding uses trailing zeros of first byte to indicate total size:
    - 1 byte:  value 0-127,       (value << 1 | 1) as ui8
    - 2 bytes: value 128-16383,   (value << 2 | 2) as ui16 LE
    - 3 bytes: value up to 2^21,  (value << 3 | 4) as ui24 LE
    - ...
    - 8 bytes: value up to 2^56,  (value << 8 | 128) as ui64 LE
    - 9 bytes: 0x00 prefix + 8 raw bytes (ui64 LE) for full 64-bit range
    """
    if value < 0:
        raise ValueError("SizeT cannot encode negative values")

    # Determine how many 7-bit chunks are needed
    if value == 0:
        return b'\x01'  # (0 << 1 | 1) = 1

    # Find minimum bytes needed
    # Based on: (63 - clz(value | 1)) / 7 + 1
    bit_len = value.bit_length()
    n_bytes = (bit_len + 6) // 7  # ceil(bit_len / 7)

    if n_bytes > 8:
        # 9-byte encoding: 0x00 prefix + raw ui64 LE
        return b'\x00' + struct.pack('<Q', value)

    # n_bytes encoding: shift value left by n_bytes, set marker bit
    marker = 1 << (n_bytes - 1)  # bit position for the marker
    encoded = (value << n_bytes) | marker
    return encoded.to_bytes(n_bytes, 'little')


def sizet_decode(data, offset=0):
    """Decode a SizeT value from data at offset.

    Returns (value, bytes_consumed).
    """
    if offset >= len(data):
        raise ValueError("SizeT: not enough data")

    first_byte = data[offset]

    if first_byte == 0x00:
        # 9-byte encoding: next 8 bytes are raw ui64 LE
        if offset + 9 > len(data):
            raise ValueError("SizeT: not enough data for 9-byte encoding")
        value = struct.unpack_from('<Q', data, offset + 1)[0]
        return value, 9

    # Count trailing zeros of (first_byte | 0x100) to get total size
    # This effectively counts trailing zeros of first_byte, capped at 8
    val = first_byte | 0x100
    n_bytes = 0
    while (val & 1) == 0:
        n_bytes += 1
        val >>= 1
    n_bytes += 1  # The formula is ctz + 1

    if offset + n_bytes > len(data):
        raise ValueError(f"SizeT: need {n_bytes} bytes, have {len(data) - offset}")

    # Read n_bytes as little-endian integer
    raw = int.from_bytes(data[offset:offset + n_bytes], 'little')

    # Shift right by n_bytes to remove the prefix marker
    value = raw >> n_bytes

    return value, n_bytes


# ---------------------------------------------------------------------------
# SerializableHeader: type name + version + payload size
# ---------------------------------------------------------------------------

def serialize_header_encode(type_name, version, payload_size):
    """Encode a thekogans SerializableHeader.

    Format: SizeT(strlen) + type_string + ui16 BE version + SizeT(payload_size)
    """
    type_bytes = type_name.encode('utf-8')
    result = sizet_encode(len(type_bytes))
    result += type_bytes
    result += struct.pack('>H', version)
    result += sizet_encode(payload_size)
    return result


def serialize_header_decode(data, offset=0):
    """Decode a SerializableHeader from data.

    Returns (type_name, version, payload_size, bytes_consumed).
    """
    pos = offset

    # Type string: SizeT(len) + raw bytes
    str_len, consumed = sizet_decode(data, pos)
    pos += consumed
    if pos + str_len > len(data):
        raise ValueError("SerializableHeader: type string truncated")
    type_name = data[pos:pos + str_len].decode('utf-8')
    pos += str_len

    # Version: ui16 BE
    if pos + 2 > len(data):
        raise ValueError("SerializableHeader: version truncated")
    version = struct.unpack_from('>H', data, pos)[0]
    pos += 2

    # Payload size: SizeT
    payload_size, consumed = sizet_decode(data, pos)
    pos += consumed

    return type_name, version, payload_size, pos - offset


# ---------------------------------------------------------------------------
# FrameHeader: keyId + ciphertextLength
# ---------------------------------------------------------------------------

def frame_header_encode(key_id, ciphertext_length):
    """Encode a FrameHeader (36 bytes).

    key_id: 32 bytes
    ciphertext_length: ui32 BE
    """
    if len(key_id) != 32:
        raise ValueError(f"keyId must be 32 bytes, got {len(key_id)}")
    return key_id + struct.pack('>I', ciphertext_length)


def frame_header_decode(data, offset=0):
    """Decode a FrameHeader from data.

    Returns (key_id, ciphertext_length).
    """
    if offset + FRAME_HEADER_SIZE > len(data):
        raise ValueError("FrameHeader: not enough data")
    key_id = data[offset:offset + 32]
    ct_len = struct.unpack_from('>I', data, offset + 32)[0]
    return key_id, ct_len


# ---------------------------------------------------------------------------
# CiphertextHeader: ivLen + ctLen + macLen (inside ciphertext block)
# ---------------------------------------------------------------------------

CIPHERTEXT_HEADER_SIZE = 8


def ciphertext_header_encode(iv_len, ct_len, mac_len):
    """Encode a CiphertextHeader (8 bytes, big-endian)."""
    return struct.pack('>HIH', iv_len, ct_len, mac_len)


def ciphertext_header_decode(data, offset=0):
    """Decode a CiphertextHeader. Returns (iv_len, ct_len, mac_len)."""
    if offset + CIPHERTEXT_HEADER_SIZE > len(data):
        raise ValueError("CiphertextHeader: not enough data")
    iv_len, ct_len, mac_len = struct.unpack_from('>HIH', data, offset)
    return iv_len, ct_len, mac_len


# ---------------------------------------------------------------------------
# PlaintextHeader: randomLength + flags
# ---------------------------------------------------------------------------

def plaintext_header_encode(random_length, flags):
    """Encode PlaintextHeader (2 bytes)."""
    return struct.pack('BB', random_length, flags)


def plaintext_header_decode(data, offset=0):
    """Decode PlaintextHeader. Returns (random_length, flags)."""
    if offset + 2 > len(data):
        raise ValueError("PlaintextHeader: not enough data")
    return data[offset], data[offset + 1]


# ---------------------------------------------------------------------------
# Session::Header
# ---------------------------------------------------------------------------

def session_header_encode(session_id, sequence):
    """Encode Session::Header.

    session_id: 16 bytes (GUID)
    sequence: ui64 BE (8 bytes)
    Total: 24 bytes.
    """
    if len(session_id) != 16:
        raise ValueError(f"session_id must be 16 bytes, got {len(session_id)}")
    return session_id + struct.pack('>Q', sequence)


def session_header_decode(data, offset=0):
    """Decode Session::Header. Returns (session_id, sequence)."""
    if offset + SESSION_HEADER_SIZE > len(data):
        raise ValueError("Session::Header: not enough data")
    session_id = data[offset:offset + 16]
    sequence = struct.unpack_from('>Q', data, offset + 16)[0]
    return session_id, sequence


# ---------------------------------------------------------------------------
# Full packet encryption/decryption (Marconi wire format)
# ---------------------------------------------------------------------------

def marconi_encrypt(key_id, aes_key, plaintext, session=None):
    """Encrypt a payload into a complete Marconi frame.

    Returns the full wire bytes: FrameHeader + CiphertextBlock

    Args:
        key_id: 32-byte key identifier
        aes_key: 32-byte AES-256-GCM key
        plaintext: the Packet payload bytes (SerializableHeader + data)
        session: optional (session_id_16B, outbound_sequence) tuple
    """
    # Build the plaintext with PlaintextHeader + random padding + session + packet
    random_length = int.from_bytes(os.urandom(1), 'big') % (MAX_RANDOM_LENGTH + 1)
    random_padding = os.urandom(random_length)

    flags = 0
    if session:
        flags |= FLAGS_SESSION_HEADER

    inner = plaintext_header_encode(random_length, flags)
    inner += random_padding
    if session:
        sess_id, seq = session
        inner += session_header_encode(sess_id, seq)
    inner += plaintext

    # AES-256-GCM encrypt
    iv = os.urandom(GCM_IV_LEN)
    aesgcm = AESGCM(aes_key)
    ct_with_tag = aesgcm.encrypt(iv, inner, None)
    ciphertext = ct_with_tag[:-GCM_TAG_LEN]
    tag = ct_with_tag[-GCM_TAG_LEN:]

    # Build ciphertext block: CiphertextHeader + IV + ciphertext + tag
    ct_block = ciphertext_header_encode(GCM_IV_LEN, len(ciphertext), GCM_TAG_LEN)
    ct_block += iv + ciphertext + tag

    # Build frame: FrameHeader + ciphertext block
    frame = frame_header_encode(key_id, len(ct_block))
    frame += ct_block

    return frame


def marconi_decrypt(data, get_key_for_id):
    """Decrypt a complete Marconi frame.

    Args:
        data: raw bytes starting with FrameHeader
        get_key_for_id: callable(key_id_32B) -> aes_key_32B or None

    Returns dict with:
        key_id, packet_type, packet_version, packet_data,
        session_id, sequence, flags
    Or None on failure.
    """
    if len(data) < FRAME_HEADER_SIZE:
        return None

    key_id, ct_total_len = frame_header_decode(data, 0)

    if FRAME_HEADER_SIZE + ct_total_len > len(data):
        logger.debug("Frame truncated: need %d, have %d",
                      FRAME_HEADER_SIZE + ct_total_len, len(data))
        return None

    aes_key = get_key_for_id(key_id)
    if aes_key is None:
        logger.debug("Unknown keyId: %s", key_id.hex()[:16])
        return None

    ct_block = data[FRAME_HEADER_SIZE:FRAME_HEADER_SIZE + ct_total_len]

    # Parse ciphertext header
    iv_len, ct_len, mac_len = ciphertext_header_decode(ct_block, 0)
    pos = CIPHERTEXT_HEADER_SIZE

    if pos + iv_len + ct_len + mac_len > len(ct_block):
        logger.debug("Ciphertext block truncated")
        return None

    iv = ct_block[pos:pos + iv_len]
    pos += iv_len
    ciphertext = ct_block[pos:pos + ct_len]
    pos += ct_len
    tag = ct_block[pos:pos + mac_len]

    # Decrypt
    aesgcm = AESGCM(aes_key)
    try:
        plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
    except Exception as e:
        logger.debug("Decryption failed: %s", e)
        return None

    # Parse plaintext
    random_length, flags = plaintext_header_decode(plaintext, 0)
    pos = 2 + random_length  # skip header + random padding

    session_id = None
    sequence = None
    if flags & FLAGS_SESSION_HEADER:
        session_id, sequence = session_header_decode(plaintext, pos)
        pos += SESSION_HEADER_SIZE

    # Parse SerializableHeader
    try:
        pkt_type, pkt_ver, pkt_size, hdr_consumed = serialize_header_decode(
            plaintext, pos
        )
        pos += hdr_consumed
        pkt_data = plaintext[pos:pos + pkt_size]
    except ValueError as e:
        logger.debug("SerializableHeader parse error: %s", e)
        return None

    return {
        "key_id": key_id,
        "packet_type": pkt_type,
        "packet_version": pkt_ver,
        "packet_data": pkt_data,
        "session_id": session_id,
        "sequence": sequence,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Packet builders for Marconi handshake packets
# ---------------------------------------------------------------------------

def build_packet_payload(type_name, version, payload_bytes):
    """Build SerializableHeader + payload for embedding in a Marconi frame."""
    header = serialize_header_encode(type_name, version, len(payload_bytes))
    return header + payload_bytes


def build_client_key_exchange(cipher_suite, public_key_bytes, key_id,
                               salt=b'', key_length=32, msg_digest="SHA2-256",
                               count=1):
    """Build a ClientKeyExchangePacket payload.

    This is the packet data (after SerializableHeader) for the
    initial key exchange. Format based on thekogans DHEParams serialization.
    """
    # CipherSuite string
    payload = sizet_encode(len(cipher_suite))
    payload += cipher_suite.encode('utf-8')

    # DHEParams: encode the key exchange parameters
    # id (for the resulting symmetric key)
    payload += key_id  # 32 bytes

    # Public key bytes (X25519 = 32 bytes)
    payload += sizet_encode(len(public_key_bytes))
    payload += public_key_bytes

    # Salt
    payload += sizet_encode(len(salt))
    payload += salt

    # Key length
    payload += struct.pack('>I', key_length)

    # Message digest name
    md_bytes = msg_digest.encode('utf-8')
    payload += sizet_encode(len(md_bytes))
    payload += md_bytes

    # Iteration count
    payload += struct.pack('>I', count)

    return build_packet_payload("ClientKeyExchangePacket", 1, payload)


# ---------------------------------------------------------------------------
# Key derivation helpers (Marconi-compatible)
# ---------------------------------------------------------------------------

def derive_marconi_key(our_private_key, their_public_bytes, salt=b'',
                       our_public_bytes=None, key_length=32,
                       msg_digest_name="SHA2-256", count=1):
    """Derive a shared symmetric key using Marconi-compatible ECDH + HKDF.

    Uses X25519 ECDH to compute shared secret, then HKDF-SHA256 to derive
    the AES key. The salt is combined with both public keys (initiator first).
    """
    their_public = X25519PublicKey.from_public_bytes(their_public_bytes)
    shared_secret = our_private_key.exchange(their_public)

    # Combine salt with public keys (thekogans style)
    if our_public_bytes is None:
        our_public_bytes = our_private_key.public_key().public_bytes_raw()
    combined_salt = salt + our_public_bytes + their_public_bytes

    hkdf = HKDF(
        algorithm=SHA256(),
        length=key_length,
        salt=combined_salt if combined_salt else None,
        info=b"thekogans_key_exchange",
    )
    return hkdf.derive(shared_secret)


def generate_key_id():
    """Generate a random 32-byte key identifier (Serializable ID)."""
    return os.urandom(32)


# ---------------------------------------------------------------------------
# UDP Beacon helpers
# ---------------------------------------------------------------------------

def parse_udp_beacon(data, source_addr=None):
    """Attempt to parse a UDP discovery beacon.

    Beacons may be:
    1. thekogans encrypted frame (starts with 32B keyId + 4B length)
    2. Raw binary with embedded X25519 pubkey
    3. JSON plaintext (JuhRadialMX format)

    Returns a dict with parsed fields, or None if unparseable.
    """
    if not data:
        return None

    result = {
        "raw_size": len(data),
        "source": source_addr,
        "format": "unknown",
    }

    # Try JSON first (our own format)
    try:
        import json
        text = data.decode('utf-8')
        msg = json.loads(text)
        result["format"] = "json"
        result["data"] = msg
        return result
    except (UnicodeDecodeError, ValueError):
        pass

    # Check for FrameHeader format (encrypted beacon)
    if len(data) >= FRAME_HEADER_SIZE:
        key_id = data[0:32]
        try:
            ct_len = struct.unpack_from('>I', data, 32)[0]
            if FRAME_HEADER_SIZE + ct_len == len(data) and ct_len > 0:
                result["format"] = "marconi_frame"
                result["key_id"] = key_id
                result["ciphertext_length"] = ct_len
                # Parse CiphertextHeader if enough data
                if ct_len >= CIPHERTEXT_HEADER_SIZE:
                    iv_len, inner_ct_len, mac_len = ciphertext_header_decode(
                        data, FRAME_HEADER_SIZE
                    )
                    result["iv_length"] = iv_len
                    result["inner_ct_length"] = inner_ct_len
                    result["mac_length"] = mac_len
                return result
        except struct.error:
            pass

    # Unknown binary format - dump structure hints
    result["format"] = "binary"
    result["hex_preview"] = data[:64].hex()
    return result


def hex_dump(data, prefix=""):
    """Format bytes as hex dump for protocol analysis."""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f"{prefix}{i:04x}: {hex_part:<48s}  {ascii_part}")
    return '\n'.join(lines)
