"""Screen edge cursor monitoring with dwell detection.

Polls cursor position and detects when the cursor dwells at a screen
boundary, firing a callback for cursor handoff.
"""

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .constants import (
    EDGE_THRESHOLD_PX,
    EDGE_DWELL_MS,
    EDGE_POLL_INTERVAL_MS,
    EDGE_IDLE_POLL_INTERVAL_MS,
    EDGE_NEAR_ZONE_PX,
    EDGE_COOLDOWN_MS,
    EDGE_VELOCITY_INSTANT_PX_PER_S,
    EDGE_INDICATOR_ZONE_PX,
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
        self._restart_waiter: Optional[threading.Thread] = None
        self._restart_pending = False
        self._restart_generation: Optional[int] = None
        self._pending_start_generation: Optional[int] = None
        self._generation = 0
        self._starting_generation: Optional[int] = None
        self._active_generation: Optional[int] = None
        self._lifecycle_lock = threading.Lock()
        self._lifecycle_changed = threading.Condition(self._lifecycle_lock)
        self._callback_fence = threading.RLock()
        self._callback_depth = 0
        self._wake_event = threading.Event()

        # Callback: on_edge_hit(edge: str, cx: int, cy: int, screen: dict)
        self.on_edge_hit: Optional[Callable] = None

        # Timing state
        self._dwell_start: Optional[float] = None
        self._dwell_edge: Optional[str] = None
        self._last_fire_time: float = 0.0
        self._suppress_until: float = 0.0

        # Velocity tracking for instant trigger
        self._prev_pos: Optional[tuple] = None
        self._prev_time: float = 0.0

        # Config cache
        self._extend_edge_zone = False
        self._flow_direction = "right"
        self._flow_monitor = ""  # "" = any monitor, "DP-3" = specific
        self._edge_sensitivity = 50  # 0-100, scales the dwell threshold
        self._config_mtime: float = 0.0

        # Cached flow monitor geometry (set from main thread, avoids Qt from bg thread)
        self._flow_monitor_geom: Optional[dict] = None

    def set_enabled(self, enabled: bool):
        """Enable/disable edge detection."""
        self._enabled = enabled
        if enabled:
            logger.info("Edge detection enabled")
        else:
            logger.info("Edge detection disabled")
            self._reset_dwell()
        self._wake_event.set()

    def cache_monitor_geometry(self):
        """Cache flow monitor geometry from Qt (call from main thread only).

        Must be called before start() so the background polling thread
        can filter by monitor without touching Qt APIs.
        """
        if not self._flow_monitor:
            self._reload_config()
        if not self._flow_monitor:
            return
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                for s in app.screens():
                    if s.name() == self._flow_monitor:
                        g = s.geometry()
                        self._flow_monitor_geom = {
                            "x": g.x(), "y": g.y(),
                            "width": g.width(), "height": g.height(),
                        }
                        logger.info("Cached edge detector monitor %s: %s",
                                    self._flow_monitor, self._flow_monitor_geom)
                        return
        except Exception as e:
            logger.debug("Qt monitor cache failed: %s", e)

    def start(self):
        """Start the polling thread."""
        with self._lifecycle_changed:
            if self._running:
                return
            if self._starting_generation is not None:
                # A stop may have invalidated a start while it was loading
                # config. Preserve one later request until that stale
                # reservation clears; concurrent requests coalesce onto it.
                if (
                    self._starting_generation != self._generation
                    and self._pending_start_generation is None
                ):
                    self._generation += 1
                    self._pending_start_generation = self._generation
                return
            self._generation += 1
            generation = self._generation
            self._starting_generation = generation

        while generation is not None:
            try:
                self._reload_config()  # Load direction/monitor before first poll
                self.cache_monitor_geometry()  # Cache geometry while on main thread
            except Exception:
                with self._lifecycle_changed:
                    if self._starting_generation == generation:
                        self._starting_generation = None
                    next_generation = self._claim_pending_start_locked()
                    self._lifecycle_changed.notify_all()
                if next_generation is not None:
                    generation = next_generation
                    continue
                raise

            with self._lifecycle_changed:
                if self._starting_generation == generation:
                    self._starting_generation = None
                next_generation = self._claim_pending_start_locked()
                self._lifecycle_changed.notify_all()
                if next_generation is not None:
                    generation = next_generation
                    continue
                if generation != self._generation or self._running:
                    return
                thread = self._thread
                if thread is not None and thread.is_alive():
                    self._restart_pending = True
                    self._restart_generation = generation
                    waiter = self._restart_waiter
                    if waiter is None or not waiter.is_alive():
                        waiter = threading.Thread(
                            target=self._restart_after,
                            args=(thread,),
                            daemon=True,
                        )
                        self._restart_waiter = waiter
                        waiter.start()
                    logger.warning("Edge detector thread is still stopping; restart queued")
                    return
                self._thread = None
                self._start_thread_locked(generation)
                return

    def _claim_pending_start_locked(self) -> Optional[int]:
        """Claim one queued start after an invalidated reservation clears."""
        generation = self._pending_start_generation
        self._pending_start_generation = None
        if generation is None or generation != self._generation or self._running:
            return None
        self._starting_generation = generation
        return generation

    def _start_thread_locked(self, generation: int):
        """Start one reserved poll generation with ``_lifecycle_lock`` held."""
        if generation != self._generation:
            return
        # A prior worker may have resumed from a blocked cursor query and
        # written sample state after stop() reset it. Every path here has
        # already proved that worker terminal, so reset immediately before
        # publishing the replacement generation.
        self._reset_generation_state()
        self._wake_event.clear()
        self._running = True
        self._active_generation = generation
        self._restart_pending = False
        self._restart_generation = None
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(generation,),
            daemon=True,
        )
        self._thread.start()
        logger.info("Edge detector started (poll: %dms, direction: %s, monitor: %s)",
                     EDGE_POLL_INTERVAL_MS, self._flow_direction, self._flow_monitor)

    def _restart_after(self, previous: threading.Thread):
        """Wait off the UI thread before replacing a stopping generation."""
        previous.join()
        with self._lifecycle_changed:
            if self._thread is previous:
                self._thread = None
            self._restart_waiter = None
            generation = self._restart_generation
            if (
                self._restart_pending
                and generation is not None
                and generation == self._generation
            ):
                self._start_thread_locked(generation)
            else:
                self._restart_pending = False
                self._restart_generation = None
            self._lifecycle_changed.notify_all()

    def stop(self):
        """Invalidate callbacks, request stop, and report lifecycle quiescence."""
        deadline = time.monotonic() + 0.2
        with self._lifecycle_changed:
            # Invalidate both a published worker and any start() that already
            # reserved a generation but is still loading main-thread config.
            self._generation += 1
            self._active_generation = None
            self._running = False
            self._restart_pending = False
            self._restart_generation = None
            self._pending_start_generation = None
            thread = self._thread

        self._reset_dwell()
        self._wake_event.set()

        # A callback that passed its generation check owns this fence until it
        # returns. Spend only the remaining stop budget crossing it; arbitrary
        # user callbacks must not turn the 200 ms lifecycle deadline into an
        # unbounded wait. A re-entrant stop from inside the callback can acquire
        # the RLock, so callback depth is part of the quiescence proof.
        callback_quiescent = False
        remaining = max(0.0, deadline - time.monotonic())
        callback_fence_acquired = self._callback_fence.acquire(timeout=remaining)
        if callback_fence_acquired:
            try:
                callback_quiescent = self._callback_depth == 0
            finally:
                self._callback_fence.release()

        with self._lifecycle_changed:
            while self._starting_generation is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._lifecycle_changed.wait(timeout=remaining)

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

        with self._lifecycle_changed:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None
            return (
                callback_quiescent
                and self._thread is None
                and self._starting_generation is None
            )

    def suppress_for(self, ms: int):
        """Suppress edge detection for ms milliseconds (prevents bounce-back)."""
        self._suppress_until = time.monotonic() + ms / 1000.0
        self._reset_dwell()
        self._wake_event.set()
        logger.debug("Edge detection suppressed for %dms", ms)

    def _reset_dwell(self):
        self._dwell_start = None
        self._dwell_edge = None

    def _reset_generation_state(self):
        """Clear edge sample state owned by one polling generation."""
        self._reset_dwell()
        self._prev_pos = None
        self._prev_time = 0.0
        self._last_fire_time = 0.0

    def _reload_config(self):
        """Reload extend_edge_zone from config (checked periodically)."""
        try:
            cfg_path = Path.home() / ".config" / "juhradial" / "config.json"
            if cfg_path.exists():
                mtime = cfg_path.stat().st_mtime
                if mtime != self._config_mtime:
                    self._config_mtime = mtime
                    cfg = json.loads(cfg_path.read_text())
                    flow = cfg.get("flow", {})
                    self._extend_edge_zone = flow.get(
                        "extend_edge_zone", False
                    )
                    self._flow_direction = flow.get("direction", "right")
                    self._flow_monitor = flow.get("monitor", "")
                    self._edge_sensitivity = flow.get("edge_sensitivity", 50)
        except Exception as e:
            # Fail-soft: a missing or malformed config keeps the previous
            # flow settings; the next mtime change retries.
            logger.debug("Flow config reload failed: %s", e)

    def _is_generation_running(self, generation: Optional[int]) -> bool:
        if generation is None:
            return self._running
        with self._lifecycle_lock:
            return (
                self._running
                and self._active_generation == generation
                and self._generation == generation
            )

    def _poll_loop(self, generation: Optional[int] = None):
        """Poll quickly near the edge and sleep until woken while disabled."""
        next_config_check = time.monotonic() + 2.0

        while self._is_generation_running(generation):
            if not self._enabled:
                self._wake_event.wait()
                self._wake_event.clear()
                continue

            now = time.monotonic()
            if now >= next_config_check:
                self._reload_config()
                next_config_check = now + 2.0

            near_edge = False
            try:
                if generation is None:
                    near_edge = self._check_edge()
                else:
                    near_edge = self._check_edge(generation)
            except Exception as e:
                logger.debug("Edge check error: %s", e)

            interval_ms = (
                EDGE_POLL_INTERVAL_MS
                if near_edge
                else EDGE_IDLE_POLL_INTERVAL_MS
            )
            self._wake_event.wait(interval_ms / 1000.0)
            self._wake_event.clear()

    def _dispatch_edge_hit(
        self,
        generation: Optional[int],
        edge: str,
        cx: int,
        cy: int,
        screen: dict,
    ) -> bool:
        """Invoke the current callback only for a still-active poll generation."""
        with self._callback_fence:
            if generation is not None:
                with self._lifecycle_lock:
                    if (
                        not self._running
                        or self._active_generation != generation
                        or self._generation != generation
                    ):
                        return False
            callback = self.on_edge_hit
            if callback is None:
                return False
            self._callback_depth += 1
            try:
                callback(edge, cx, cy, screen)
            finally:
                self._callback_depth -= 1
            return True

    def _check_edge(self, generation: Optional[int] = None):
        """Check if cursor is at a screen edge and handle dwell detection."""
        now = time.monotonic()

        # Suppression active (e.g., just received a handoff)
        if now < self._suppress_until:
            return False

        # Cooldown after last fire
        if now - self._last_fire_time < EDGE_COOLDOWN_MS / 1000.0:
            return False

        # Get cursor position and screen geometry
        try:
            from overlay.overlay_cursor import get_cursor_pos, get_screen_geometry
        except ImportError:
            from overlay_cursor import get_cursor_pos, get_screen_geometry
        pos = get_cursor_pos()
        if not pos:
            self._reset_dwell()
            self._prev_pos = None
            return False

        cx, cy = pos

        # Compute velocity (px/s) from previous sample
        velocity = 0.0
        if self._prev_pos and self._prev_time > 0:
            dt = now - self._prev_time
            if dt > 0:
                dx = cx - self._prev_pos[0]
                dy = cy - self._prev_pos[1]
                velocity = (dx * dx + dy * dy) ** 0.5 / dt
        self._prev_pos = (cx, cy)
        self._prev_time = now

        # Pass cursor pos to avoid redundant gdbus call inside get_screen_geometry
        screen = get_screen_geometry(cursor_pos=pos)

        sx = screen["x"]
        sy = screen["y"]
        sw = screen["width"]
        sh = screen["height"]

        # Filter by configured monitor: only trigger on the monitor where
        # the indicator is placed, not on every monitor's edge.
        # Uses cached geometry (set from main thread) to avoid Qt from bg thread.
        if self._flow_monitor and self._flow_monitor_geom:
            g = self._flow_monitor_geom
            if not (g["x"] == sx and g["y"] == sy
                    and g["width"] == sw and g["height"] == sh):
                self._reset_dwell()
                return False

        # Keep the original 8 ms cadence while approaching the configured edge.
        # Farther away, a 32 ms sample still detects fast slams from velocity.
        if self._flow_direction == "left":
            edge_distance = cx - sx
        elif self._flow_direction == "right":
            edge_distance = sx + sw - 1 - cx
        elif self._flow_direction == "top":
            edge_distance = cy - sy
        else:
            edge_distance = sy + sh - 1 - cy
        near_edge = edge_distance <= EDGE_NEAR_ZONE_PX

        # Only check the configured flow direction edge, not all four edges.
        edge = None
        d = self._flow_direction
        if d == "left" and cx <= sx + EDGE_THRESHOLD_PX:
            edge = "left"
        elif d == "right" and cx >= sx + sw - EDGE_THRESHOLD_PX - 1:
            edge = "right"
        elif d == "top" and cy <= sy + EDGE_THRESHOLD_PX:
            edge = "top"
        elif d == "bottom" and cy >= sy + sh - EDGE_THRESHOLD_PX - 1:
            edge = "bottom"

        if edge is None:
            self._reset_dwell()
            return near_edge

        # Restrict trigger zone to the indicator pill area only,
        # unless the user enabled "extend edge zone" for full-edge triggering.
        if not self._extend_edge_zone:
            half_zone = EDGE_INDICATOR_ZONE_PX // 2
            if edge in ("left", "right"):
                center_y = sy + sh // 2
                if abs(cy - center_y) > half_zone:
                    self._reset_dwell()
                    return near_edge
            else:  # top, bottom
                center_x = sx + sw // 2
                if abs(cx - center_x) > half_zone:
                    self._reset_dwell()
                    return near_edge

        # Velocity-based instant trigger: fast cursor slam fires immediately
        if velocity >= EDGE_VELOCITY_INSTANT_PX_PER_S:
            self._last_fire_time = now
            self._reset_dwell()
            logger.info("Edge slam: %s at (%d, %d) vel=%.0f px/s",
                        edge, cx, cy, velocity)
            self._dispatch_edge_hit(generation, edge, cx, cy, screen)
            return False

        # Track dwell time
        if edge != self._dwell_edge:
            self._dwell_start = now
            self._dwell_edge = edge
            return True

        # Check if dwell time exceeded. edge_sensitivity (0-100) scales the
        # required dwell: 100 = quick trigger (~0.2x), 0 = deliberate (~1.8x).
        sens = max(0, min(100, self._edge_sensitivity))
        dwell_needed = (EDGE_DWELL_MS / 1000.0) * (1.8 - (sens / 100.0) * 1.6)
        if self._dwell_start and (now - self._dwell_start) >= dwell_needed:
            self._last_fire_time = now
            self._reset_dwell()

            logger.info("Edge dwell: %s at (%d, %d)", edge, cx, cy)
            self._dispatch_edge_hit(generation, edge, cx, cy, screen)
            return False

        return True
