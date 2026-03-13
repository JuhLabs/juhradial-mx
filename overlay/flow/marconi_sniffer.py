#!/usr/bin/env python3
"""Marconi protocol sniffer and probe.

Listens for UDP beacons on Logi Flow discovery ports and can probe
the Mac's Marconi TCP tunnel. Captures raw packets for analysis.

Usage:
    python3 -m overlay.flow.marconi_sniffer [--listen] [--probe MAC_IP]

    --listen          Listen on UDP 59870-59871 for beacons
    --probe MAC_IP    Connect to Mac TCP 59869 and probe
    --beacon MAC_IP   Send our own beacon to Mac's discovery port
    --all MAC_IP      Do everything: listen + beacon + probe
    --duration SECS   How long to listen (default: 60)
"""

import argparse
import json
import os
import socket
import struct
import sys
import threading
import time

# Add parent paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from overlay.flow.marconi import (
    hex_dump,
    parse_udp_beacon,
)

# Logi Flow ports (default, may vary)
DISCOVERY_PORTS = [59870, 59871]
TUNNEL_PORT = 59869

# Colors for terminal output
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'


def listen_udp(ports, duration=60, broadcast_addr="255.255.255.255"):
    """Listen on UDP discovery ports for beacons."""
    socks = []
    for port in ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # CodeQL: intentional - discovery requires binding to all interfaces
            sock.bind(('0.0.0.0', port))  # nosec B104 - LAN broadcast receiver, must bind all interfaces
            sock.settimeout(1.0)
            socks.append((sock, port))
            print(f"{GREEN}[LISTEN]{RESET} Bound to UDP 0.0.0.0:{port}")
        except OSError as e:
            print(f"{RED}[ERROR]{RESET} Cannot bind UDP {port}: {e}")

    if not socks:
        return

    # Get our own IP to filter self-beacons
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except OSError:
        local_ip = "127.0.0.1"

    print(f"{CYAN}[INFO]{RESET} Local IP: {local_ip}")
    print(f"{CYAN}[INFO]{RESET} Listening for {duration}s... (press Ctrl+C to stop)\n")

    start = time.time()
    packet_count = 0

    while time.time() - start < duration:
        for sock, port in socks:
            try:
                data, addr = sock.recvfrom(4096)
                if addr[0] == local_ip:
                    continue

                packet_count += 1
                elapsed = time.time() - start

                print(f"\n{YELLOW}{'=' * 70}{RESET}")
                print(f"{GREEN}[BEACON #{packet_count}]{RESET} "
                      f"Port {port} | From {addr[0]}:{addr[1]} | "
                      f"{len(data)} bytes | t={elapsed:.1f}s")
                print(f"{YELLOW}{'=' * 70}{RESET}")

                # Parse beacon
                parsed = parse_udp_beacon(data, addr)
                print(f"Format: {parsed['format']}")

                if parsed['format'] == 'json':
                    print(f"JSON data: {json.dumps(parsed['data'], indent=2)}")
                elif parsed['format'] == 'marconi_frame':
                    print(f"Key ID: {parsed['key_id'].hex()}")
                    print(f"Ciphertext length: {parsed['ciphertext_length']}")
                    if 'iv_length' in parsed:
                        print(f"IV length: {parsed['iv_length']}")
                        print(f"Inner CT length: {parsed['inner_ct_length']}")
                        print(f"MAC length: {parsed['mac_length']}")

                print(f"\n{BLUE}Raw hex dump:{RESET}")
                print(hex_dump(data))

                # Save to file
                fname = f"/tmp/marconi_beacon_{packet_count}_{addr[0]}_{port}.bin"
                with open(fname, 'wb') as f:
                    f.write(data)
                print(f"\n{CYAN}Saved to {fname}{RESET}")

            except socket.timeout:
                continue
            except KeyboardInterrupt:
                break

    for sock, _ in socks:
        sock.close()

    print(f"\n{CYAN}[DONE]{RESET} Captured {packet_count} beacon(s)")


def _read_machine_id():
    """Read machine-id from /etc/machine-id, truncated to 16 chars."""
    with open("/etc/machine-id") as f:
        return f.read().strip()[:16]


def send_beacon(mac_ip, ports=None):
    """Send a JuhRadialMX discovery beacon to the Mac."""
    if ports is None:
        ports = DISCOVERY_PORTS

    # Generate an X25519 keypair for this probe
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    private_key = X25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes_raw()

    # Get our hostname and IP
    hostname = socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except OSError:
        local_ip = "0.0.0.0"

    beacon = json.dumps({
        "hostname": hostname,
        "ip": local_ip,
        "port": TUNNEL_PORT,
        "platform": "linux",
        "software": "JuhRadialMX",
        "flow_version": "1.0",
        "public_key": public_bytes.hex(),
        "machine_id": _read_machine_id(),
    }).encode('utf-8')

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    for port in ports:
        try:
            # Send directly to Mac IP
            sock.sendto(beacon, (mac_ip, port))
            print(f"{GREEN}[SENT]{RESET} Beacon to {mac_ip}:{port} ({len(beacon)} bytes)")

            # Also broadcast
            sock.sendto(beacon, ("255.255.255.255", port))
            print(f"{GREEN}[SENT]{RESET} Broadcast beacon on port {port}")
        except OSError as e:
            print(f"{RED}[ERROR]{RESET} Send to port {port}: {e}")

    sock.close()
    print(f"\n{CYAN}Our X25519 pubkey: {public_bytes.hex()}{RESET}")
    return private_key, public_bytes


def probe_tcp(mac_ip, port=TUNNEL_PORT, timeout=5):
    """Probe the Mac's Marconi TCP tunnel.

    Tries several approaches:
    1. Connect and wait (see if Mac sends anything first)
    2. Send minimal FrameHeader with various keyIds
    3. Send our ClientKeyExchangePacket
    """
    print(f"\n{YELLOW}{'=' * 70}{RESET}")
    print(f"{BLUE}[PROBE]{RESET} Connecting to {mac_ip}:{port}...")

    # Test 1: Connect and listen
    print(f"\n{CYAN}--- Test 1: Connect and wait (does Mac speak first?) ---{RESET}")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((mac_ip, port))
        print(f"{GREEN}Connected!{RESET}")

        try:
            data = sock.recv(4096)
            if data:
                print(f"{GREEN}Mac sent {len(data)} bytes first!{RESET}")
                print(hex_dump(data))
                with open("/tmp/marconi_tcp_server_hello.bin", 'wb') as f:
                    f.write(data)
            else:
                print(f"{YELLOW}Mac closed connection (empty recv){RESET}")
        except socket.timeout:
            print(f"{YELLOW}Mac is waiting for us to speak first (timeout){RESET}")

        sock.close()
    except (ConnectionRefusedError, OSError) as e:
        print(f"{RED}Connection failed: {e}{RESET}")
        return

    # Test 2: Send FrameHeader with known Mac node_id as keyId
    mac_node_id = bytes.fromhex(
        "27e1688a88530f0d0e96fcf41599ee093db0538ce389b3cfc6eadf4d65d138cb"
    )
    print(f"\n{CYAN}--- Test 2: Send FrameHeader with Mac's node_id as keyId ---{RESET}")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((mac_ip, port))

        # Minimal valid frame: keyId + ctLen=100 (will trigger key lookup)
        frame_header = mac_node_id + struct.pack('>I', 100)
        sock.sendall(frame_header)
        print(f"Sent FrameHeader ({len(frame_header)} bytes)")

        try:
            data = sock.recv(4096)
            if data:
                print(f"{GREEN}Mac responded with {len(data)} bytes!{RESET}")
                print(hex_dump(data))
            else:
                print(f"{YELLOW}Mac closed connection (key not in KeyRing){RESET}")
        except socket.timeout:
            print(f"{YELLOW}Mac is waiting for ciphertext ({100} bytes promised){RESET}")
            # Send dummy ciphertext to trigger response
            sock.sendall(os.urandom(100))
            try:
                data = sock.recv(4096)
                if data:
                    print(f"{GREEN}Mac responded: {len(data)} bytes{RESET}")
                    print(hex_dump(data))
                else:
                    print(f"{YELLOW}Mac closed after receiving ciphertext{RESET}")
            except socket.timeout:
                print(f"{YELLOW}No response after ciphertext{RESET}")

        sock.close()
    except (ConnectionRefusedError, OSError) as e:
        print(f"{RED}Connection failed: {e}{RESET}")

    # Test 3: Try with all-zeros keyId
    print(f"\n{CYAN}--- Test 3: Send FrameHeader with zero keyId ---{RESET}")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((mac_ip, port))

        frame_header = b'\x00' * 32 + struct.pack('>I', 50)
        sock.sendall(frame_header)
        sock.sendall(os.urandom(50))

        try:
            data = sock.recv(4096)
            if data:
                print(f"{GREEN}Mac responded: {len(data)} bytes{RESET}")
                print(hex_dump(data))
            else:
                print(f"{YELLOW}Mac closed connection{RESET}")
        except socket.timeout:
            print(f"{YELLOW}No response{RESET}")

        sock.close()
    except (ConnectionRefusedError, OSError) as e:
        print(f"{RED}Connection failed: {e}{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Marconi protocol sniffer and probe")
    parser.add_argument('--listen', action='store_true',
                        help='Listen for UDP beacons')
    parser.add_argument('--probe', metavar='MAC_IP',
                        help='Probe Mac TCP tunnel')
    parser.add_argument('--beacon', metavar='MAC_IP',
                        help='Send beacon to Mac')
    parser.add_argument('--all', metavar='MAC_IP',
                        help='Listen + beacon + probe')
    parser.add_argument('--duration', type=int, default=60,
                        help='Listen duration in seconds')
    parser.add_argument('--ports', metavar='PORT', nargs='+', type=int,
                        default=DISCOVERY_PORTS,
                        help='UDP ports to listen on')
    args = parser.parse_args()

    if args.all:
        mac_ip = args.all
        # Start listener in background
        listener = threading.Thread(
            target=listen_udp,
            args=(args.ports, args.duration),
            daemon=True,
        )
        listener.start()

        time.sleep(1)  # Let listener bind

        # Send beacons
        send_beacon(mac_ip, args.ports)

        time.sleep(2)  # Wait for responses

        # Probe TCP
        probe_tcp(mac_ip)

        # Wait for listener
        print(f"\n{CYAN}[INFO]{RESET} Listener running for {args.duration}s...")
        print(f"{CYAN}[INFO]{RESET} Open Logi Options+ > Flow > 'Set up' on Mac to trigger beacons")
        listener.join()

    elif args.listen:
        listen_udp(args.ports, args.duration)

    elif args.beacon:
        send_beacon(args.beacon, args.ports)

    elif args.probe:
        probe_tcp(args.probe)

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
