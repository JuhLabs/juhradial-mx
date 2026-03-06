"""Screen edge cursor monitoring with dwell detection.

Polls cursor position and detects when the cursor dwells at a screen
boundary, firing a callback for cursor handoff.
"""

import logging
import threading
import time
from typing import Callable, Optional

from .constants import (
    EDGE_THRESHOLD_PX,
    EDGE_DWELL_MS,
    EDGE_POLL_INTERVAL_MS,
    EDGE_COOLDOWN_MS,
)

logger = logging.getLogger("juhradial.flow.edge")


class ScreenEdgeDetector:
    """Monitors cursor position and detects screen edge dwelling.

    Fires on_edge_hit(edge, cx, cy, screen_info) when cursor dwells
    at a screen boundary for EDGE_DWELL_MS.
    """

    def __init__(self):
        self._enabled = False
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Callback: on_edge_hit(edge: str, cx: int, cy: int, screen: dict)
        self.on_edge_hit: Optional[Callable] = None

        # Timing state
        self._dwell_start: Optional[float] = None
        self._dwell_edge: Optional[str] = None
        self._last_fire_time: float = 0.0
        self._suppress_until: float = 0.0

    def set_enabled(self, enabled: bool):
        """Enable/disable edge detection."""
        self._enabled = enabled
        if enabled:
            logger.info("Edge detection enabled")
        else:
            logger.info("Edge detection disabled")
            self._reset_dwell()

    def start(self):
        """Start the polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Edge detector started (poll: %dms)", EDGE_POLL_INTERVAL_MS)

    def stop(self):
        """Stop the polling thread."""
        self._running = False
        self._reset_dwell()

    def suppress_for(self, ms: int):
        """Suppress edge detection for ms milliseconds (prevents bounce-back)."""
        self._suppress_until = time.monotonic() + ms / 1000.0
        self._reset_dwell()
        logger.debug("Edge detection suppressed for %dms", ms)

    def _reset_dwell(self):
        self._dwell_start = None
        self._dwell_edge = None

    def _poll_loop(self):
        """Main polling loop - checks cursor position at EDGE_POLL_INTERVAL_MS."""
        poll_interval = EDGE_POLL_INTERVAL_MS / 1000.0

        while self._running:
            if self._enabled:
                try:
                    self._check_edge()
                except Exception as e:
                    logger.debug("Edge check error: %s", e)

            time.sleep(poll_interval)

    def _check_edge(self):
        """Check if cursor is at a screen edge and handle dwell detection."""
        now = time.monotonic()

        # Suppression active (e.g., just received a handoff)
        if now < self._suppress_until:
            return

        # Cooldown after last fire
        if now - self._last_fire_time < EDGE_COOLDOWN_MS / 1000.0:
            return

        # Get cursor position and screen geometry
        try:
            from overlay.overlay_cursor import get_cursor_pos, get_screen_geometry
        except ImportError:
            from overlay_cursor import get_cursor_pos, get_screen_geometry
        pos = get_cursor_pos()
        if not pos:
            self._reset_dwell()
            return

        cx, cy = pos
        screen = get_screen_geometry()

        sx = screen["x"]
        sy = screen["y"]
        sw = screen["width"]
        sh = screen["height"]

        # Detect which edge (if any) the cursor is at
        edge = None
        if cx <= sx + EDGE_THRESHOLD_PX:
            edge = "left"
        elif cx >= sx + sw - EDGE_THRESHOLD_PX - 1:
            edge = "right"
        elif cy <= sy + EDGE_THRESHOLD_PX:
            edge = "top"
        elif cy >= sy + sh - EDGE_THRESHOLD_PX - 1:
            edge = "bottom"

        if edge is None:
            self._reset_dwell()
            return

        # Track dwell time
        if edge != self._dwell_edge:
            self._dwell_start = now
            self._dwell_edge = edge
            return

        # Check if dwell time exceeded
        if self._dwell_start and (now - self._dwell_start) >= EDGE_DWELL_MS / 1000.0:
            self._last_fire_time = now
            self._reset_dwell()

            logger.info("Edge hit: %s at (%d, %d)", edge, cx, cy)
            if self.on_edge_hit:
                self.on_edge_hit(edge, cx, cy, screen)
