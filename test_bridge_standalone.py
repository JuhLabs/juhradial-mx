#!/usr/bin/env python3
"""Standalone JuhFlow bridge test - starts ONLY the bridge server.

Use this to test the Mac <-> Linux connection without running the full overlay.

Usage (Linux):
    python3 test_bridge_standalone.py

Usage (Mac):
    python3 juhflow/juhflow_app.py --ip 192.168.68.74 --cli

What it does:
    1. Starts the JuhFlow bridge server on TCP 59872
    2. Broadcasts UDP discovery beacons on port 59873
    3. Prints all incoming messages from JuhFlow Mac clients
    4. Sends a test edge_hit every 10 seconds to connected peers
"""

import logging
import signal
import sys
import time

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bridge-test")

# Add project root to path
sys.path.insert(0, ".")

from overlay.flow.juhflow_bridge import JuhFlowBridge


def main():
    received_count = {"edge": 0, "clipboard": 0, "device": 0, "config": 0}

    def on_edge_hit(peer_id, msg):
        received_count["edge"] += 1
        edge = msg.get("edge", "?")
        rel = msg.get("relative_position", 0)
        logger.info(
            "EDGE HIT from %s: %s edge, rel=%.2f (total: %d)",
            peer_id[:16], edge, rel, received_count["edge"],
        )

    def on_clipboard(peer_id, msg):
        received_count["clipboard"] += 1
        content = msg.get("content", "")
        logger.info(
            "CLIPBOARD from %s: %d chars (total: %d)",
            peer_id[:16], len(content), received_count["clipboard"],
        )

    def on_device_switch(peer_id, msg):
        received_count["device"] += 1
        logger.info("DEVICE SWITCH from %s: %s", peer_id[:16], msg)

    def on_config(peer_id, msg):
        received_count["config"] += 1
        logger.info("CONFIG from %s: %s", peer_id[:16], msg)

    bridge = JuhFlowBridge(
        on_edge_hit=on_edge_hit,
        on_clipboard=on_clipboard,
        on_device_switch=on_device_switch,
        on_config=on_config,
    )
    bridge.start()

    logger.info("=" * 60)
    logger.info("JuhFlow Bridge test server started")
    logger.info("  TCP server: port 59872")
    logger.info("  UDP discovery: port 59873")
    logger.info("  Local IP: %s", bridge._local_ip)
    logger.info("=" * 60)
    logger.info("Waiting for JuhFlow Mac clients...")
    logger.info("On Mac, run: python3 juhflow/juhflow_app.py --ip %s --cli", bridge._local_ip)
    logger.info("Press Ctrl+C to stop")

    def signal_handler(sig, frame):
        logger.info("Shutting down...")
        bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    test_seq = 0
    while True:
        time.sleep(5)
        peers = bridge.get_peers()
        if peers:
            for p in peers:
                age = time.time() - p["connected_at"]
                logger.info(
                    "  Peer: %s (%s, %s) - connected %.0fs",
                    p["hostname"], p["platform"], p["ip"], age,
                )

            # Send periodic test edge_hit to exercise both directions
            if test_seq % 2 == 0:
                bridge.send_edge_hit(
                    "right", (1920, 540),
                    {"x": 0, "y": 0, "width": 1920, "height": 1080},
                    relative_position=0.5,
                )
                logger.info("Sent test edge_hit #%d to %d peers", test_seq, len(peers))
            test_seq += 1
        else:
            logger.debug("No peers connected - waiting for JuhFlow clients...")


if __name__ == "__main__":
    main()
