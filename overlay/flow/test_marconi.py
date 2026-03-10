"""Tests for thekogans Marconi wire format implementation."""

import os
import struct
import unittest

from .marconi import (
    CIPHERTEXT_HEADER_SIZE,
    FRAME_HEADER_SIZE,
    FLAGS_SESSION_HEADER,
    ciphertext_header_decode,
    ciphertext_header_encode,
    frame_header_decode,
    frame_header_encode,
    generate_key_id,
    marconi_decrypt,
    marconi_encrypt,
    plaintext_header_decode,
    plaintext_header_encode,
    serialize_header_decode,
    serialize_header_encode,
    session_header_decode,
    session_header_encode,
    sizet_decode,
    sizet_encode,
)


class TestSizeT(unittest.TestCase):
    """Test thekogans SizeT variable-length integer encoding."""

    def test_zero(self):
        encoded = sizet_encode(0)
        self.assertEqual(len(encoded), 1)
        value, consumed = sizet_decode(encoded)
        self.assertEqual(value, 0)
        self.assertEqual(consumed, 1)

    def test_small_values(self):
        """Values 0-127 should encode as single byte."""
        for v in [0, 1, 42, 63, 64, 127]:
            encoded = sizet_encode(v)
            self.assertEqual(len(encoded), 1, f"Value {v} should be 1 byte")
            decoded, consumed = sizet_decode(encoded)
            self.assertEqual(decoded, v, f"Roundtrip failed for {v}")
            self.assertEqual(consumed, 1)

    def test_medium_values(self):
        """Values 128-16383 should encode as 2 bytes."""
        for v in [128, 255, 256, 1000, 8191, 16383]:
            encoded = sizet_encode(v)
            self.assertEqual(len(encoded), 2, f"Value {v} should be 2 bytes")
            decoded, consumed = sizet_decode(encoded)
            self.assertEqual(decoded, v, f"Roundtrip failed for {v}")
            self.assertEqual(consumed, 2)

    def test_larger_values(self):
        """Larger values should use 3+ bytes."""
        for v in [16384, 65535, 100000, 2**20, 2**28]:
            encoded = sizet_encode(v)
            decoded, consumed = sizet_decode(encoded)
            self.assertEqual(decoded, v, f"Roundtrip failed for {v}")
            self.assertEqual(consumed, len(encoded))

    def test_very_large(self):
        """Values requiring 9-byte encoding."""
        v = 2**60
        encoded = sizet_encode(v)
        self.assertEqual(len(encoded), 9)
        self.assertEqual(encoded[0], 0x00)
        decoded, consumed = sizet_decode(encoded)
        self.assertEqual(decoded, v)
        self.assertEqual(consumed, 9)

    def test_decode_at_offset(self):
        """Decoding from non-zero offset."""
        prefix = b'\xff\xff\xff'
        encoded = sizet_encode(42)
        data = prefix + encoded
        value, consumed = sizet_decode(data, len(prefix))
        self.assertEqual(value, 42)


class TestSerializableHeader(unittest.TestCase):

    def test_roundtrip(self):
        type_name = "ClientKeyExchangePacket"
        version = 1
        size = 256
        encoded = serialize_header_encode(type_name, version, size)
        dec_type, dec_ver, dec_size, consumed = serialize_header_decode(encoded)
        self.assertEqual(dec_type, type_name)
        self.assertEqual(dec_ver, version)
        self.assertEqual(dec_size, size)
        self.assertEqual(consumed, len(encoded))

    def test_short_name(self):
        encoded = serialize_header_encode("Ping", 0, 0)
        dec_type, dec_ver, dec_size, consumed = serialize_header_decode(encoded)
        self.assertEqual(dec_type, "Ping")
        self.assertEqual(dec_ver, 0)
        self.assertEqual(dec_size, 0)

    def test_at_offset(self):
        prefix = b'\x00' * 10
        encoded = serialize_header_encode("Test", 5, 100)
        data = prefix + encoded
        dec_type, dec_ver, dec_size, consumed = serialize_header_decode(data, 10)
        self.assertEqual(dec_type, "Test")
        self.assertEqual(dec_ver, 5)
        self.assertEqual(dec_size, 100)


class TestFrameHeader(unittest.TestCase):

    def test_roundtrip(self):
        key_id = os.urandom(32)
        ct_len = 12345
        encoded = frame_header_encode(key_id, ct_len)
        self.assertEqual(len(encoded), FRAME_HEADER_SIZE)
        dec_key_id, dec_ct_len = frame_header_decode(encoded)
        self.assertEqual(dec_key_id, key_id)
        self.assertEqual(dec_ct_len, ct_len)

    def test_wrong_key_id_size(self):
        with self.assertRaises(ValueError):
            frame_header_encode(b'\x00' * 16, 100)


class TestCiphertextHeader(unittest.TestCase):

    def test_roundtrip(self):
        encoded = ciphertext_header_encode(12, 1024, 16)
        self.assertEqual(len(encoded), CIPHERTEXT_HEADER_SIZE)
        iv_len, ct_len, mac_len = ciphertext_header_decode(encoded)
        self.assertEqual(iv_len, 12)
        self.assertEqual(ct_len, 1024)
        self.assertEqual(mac_len, 16)


class TestPlaintextHeader(unittest.TestCase):

    def test_roundtrip(self):
        encoded = plaintext_header_encode(42, FLAGS_SESSION_HEADER)
        self.assertEqual(len(encoded), 2)
        rand_len, flags = plaintext_header_decode(encoded)
        self.assertEqual(rand_len, 42)
        self.assertEqual(flags, FLAGS_SESSION_HEADER)


class TestSessionHeader(unittest.TestCase):

    def test_roundtrip(self):
        session_id = os.urandom(16)
        seq = 0xDEADBEEF
        encoded = session_header_encode(session_id, seq)
        self.assertEqual(len(encoded), 24)
        dec_id, dec_seq = session_header_decode(encoded)
        self.assertEqual(dec_id, session_id)
        self.assertEqual(dec_seq, seq)


class TestMarconiEncryptDecrypt(unittest.TestCase):
    """Test full Marconi frame encryption and decryption round-trip."""

    def test_roundtrip_no_session(self):
        key_id = generate_key_id()
        aes_key = os.urandom(32)
        payload = serialize_header_encode("HeartbeatPacket", 1, 4)
        payload += struct.pack('>I', 0)  # empty heartbeat

        frame = marconi_encrypt(key_id, aes_key, payload)

        # Verify frame structure
        self.assertGreater(len(frame), FRAME_HEADER_SIZE)
        dec_key_id, ct_len = frame_header_decode(frame)
        self.assertEqual(dec_key_id, key_id)
        self.assertEqual(len(frame), FRAME_HEADER_SIZE + ct_len)

        # Decrypt
        key_store = {key_id: aes_key}
        result = marconi_decrypt(frame, lambda kid: key_store.get(kid))
        self.assertIsNotNone(result)
        self.assertEqual(result["key_id"], key_id)
        self.assertEqual(result["packet_type"], "HeartbeatPacket")
        self.assertEqual(result["packet_version"], 1)
        self.assertEqual(result["session_id"], None)

    def test_roundtrip_with_session(self):
        key_id = generate_key_id()
        aes_key = os.urandom(32)
        session_id = os.urandom(16)
        sequence = 42

        payload = serialize_header_encode("PingPacket", 1, 0)

        frame = marconi_encrypt(
            key_id, aes_key, payload,
            session=(session_id, sequence),
        )

        key_store = {key_id: aes_key}
        result = marconi_decrypt(frame, lambda kid: key_store.get(kid))
        self.assertIsNotNone(result)
        self.assertEqual(result["packet_type"], "PingPacket")
        self.assertEqual(result["session_id"], session_id)
        self.assertEqual(result["sequence"], sequence)
        self.assertTrue(result["flags"] & FLAGS_SESSION_HEADER)

    def test_wrong_key_returns_none(self):
        key_id = generate_key_id()
        aes_key = os.urandom(32)
        payload = serialize_header_encode("Test", 1, 0)
        frame = marconi_encrypt(key_id, aes_key, payload)

        # Wrong key in store
        wrong_key = os.urandom(32)
        result = marconi_decrypt(frame, lambda kid: wrong_key)
        self.assertIsNone(result)

    def test_unknown_key_id_returns_none(self):
        key_id = generate_key_id()
        aes_key = os.urandom(32)
        payload = serialize_header_encode("Test", 1, 0)
        frame = marconi_encrypt(key_id, aes_key, payload)

        result = marconi_decrypt(frame, lambda kid: None)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
