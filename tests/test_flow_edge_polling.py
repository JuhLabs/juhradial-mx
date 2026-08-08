"""Behavioral regressions for adaptive Flow edge polling."""

import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO_ROOT / "overlay"))

import flow as flow_module
from flow import edge_detector as edge_module
from flow.constants import EDGE_IDLE_POLL_INTERVAL_MS, EDGE_POLL_INTERVAL_MS
from flow.edge_detector import ScreenEdgeDetector


class _WakeEvent:
    def __init__(self, detector):
        self.detector = detector
        self.waits = []
        self.set_calls = 0

    def wait(self, timeout=None):
        self.waits.append(timeout)
        self.detector._running = False
        return True

    def set(self):
        self.set_calls += 1

    def clear(self):
        pass


class _Thread:
    def __init__(self):
        self.join_calls = []

    def join(self, timeout=None):
        self.join_calls.append(timeout)

    def is_alive(self):
        return False


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _run_one_loop(monkeypatch, *, enabled, near_edge):
    detector = ScreenEdgeDetector()
    detector._enabled = enabled
    detector._running = True
    detector._check_edge = lambda: near_edge
    wake = _WakeEvent(detector)
    detector._wake_event = wake

    # The old implementation sleeps directly; stop it after one iteration so
    # this regression test fails rather than spinning forever on the baseline.
    monkeypatch.setattr(
        edge_module.time,
        "sleep",
        lambda _timeout: setattr(detector, "_running", False),
    )

    detector._poll_loop()
    return wake


def test_disabled_detector_waits_for_a_state_change_without_polling(monkeypatch):
    wake = _run_one_loop(monkeypatch, enabled=False, near_edge=False)

    assert wake.waits == [None]


def test_far_cursor_uses_idle_poll_interval(monkeypatch):
    wake = _run_one_loop(monkeypatch, enabled=True, near_edge=False)

    assert wake.waits == [EDGE_IDLE_POLL_INTERVAL_MS / 1000.0]


def test_near_cursor_keeps_the_existing_fast_poll_interval(monkeypatch):
    wake = _run_one_loop(monkeypatch, enabled=True, near_edge=True)

    assert wake.waits == [EDGE_POLL_INTERVAL_MS / 1000.0]


def test_state_changes_wake_the_polling_thread():
    detector = ScreenEdgeDetector()
    wake = _WakeEvent(detector)
    detector._wake_event = wake

    detector.set_enabled(True)
    detector.suppress_for(100)
    detector.stop()

    assert wake.set_calls == 3


def test_stop_waits_for_the_woken_polling_thread():
    detector = ScreenEdgeDetector()
    thread = _Thread()
    detector._thread = thread

    detector.stop()

    assert len(thread.join_calls) == 1
    assert 0.0 < thread.join_calls[0] <= 0.2
    assert detector._thread is None


def test_stop_cancels_a_start_blocked_in_config_before_owner_discard(monkeypatch):
    detector = ScreenEdgeDetector()
    config_entered = threading.Event()
    config_release = threading.Event()
    config_loads = 0

    def blocked_reload():
        nonlocal config_loads
        config_loads += 1
        config_entered.set()
        assert config_release.wait(timeout=2.0)

    monkeypatch.setattr(detector, "_reload_config", blocked_reload)
    monkeypatch.setattr(detector, "cache_monitor_geometry", lambda: None)
    for name in (
        "_flow_server",
        "_logi_flow_server",
        "_logi_discovery",
        "_presence_server",
        "_handoff_manager",
        "_juhflow_bridge",
        "_flow_indicator",
    ):
        monkeypatch.setattr(flow_module, name, None)
    monkeypatch.setattr(flow_module, "_edge_detector", detector)

    starter = threading.Thread(target=detector.start)
    try:
        starter.start()
        assert config_entered.wait(timeout=1.0)

        started = time.monotonic()
        flow_module.stop_flow_server()
        assert time.monotonic() - started < 0.75

        # Queue a replacement behind the cancelled config load, then prove a
        # later stop cancels that pending request before it can be consumed.
        detector.start()
        flow_module.stop_flow_server()

        config_release.set()
        starter.join(timeout=1.0)
        assert not starter.is_alive()
        assert config_loads == 1
        assert detector._thread is None
        assert flow_module.get_edge_detector() is detector

        assert detector.stop() is True
        flow_module.stop_flow_server()
        assert flow_module.get_edge_detector() is None
    finally:
        config_release.set()
        starter.join(timeout=1.0)
        detector.stop()
        thread = detector._thread
        if thread is not None:
            thread.join(timeout=1.0)


def test_restart_requested_after_bounded_stop_replaces_cancelled_start(monkeypatch):
    detector = ScreenEdgeDetector()
    detector._enabled = True
    first_config_entered = threading.Event()
    first_config_release = threading.Event()
    replacement_config_loaded = threading.Event()
    worker_entered = threading.Event()
    worker_release = threading.Event()
    counter_lock = threading.Lock()
    config_loads = 0
    active_workers = 0
    max_active_workers = 0
    worker_calls = 0

    def blocked_first_reload():
        nonlocal config_loads
        with counter_lock:
            config_loads += 1
            load = config_loads
        if load == 1:
            first_config_entered.set()
            assert first_config_release.wait(timeout=2.0)
        else:
            replacement_config_loaded.set()

    def blocked_check(_generation=None):
        nonlocal active_workers, max_active_workers, worker_calls
        with counter_lock:
            worker_calls += 1
            active_workers += 1
            max_active_workers = max(max_active_workers, active_workers)
        worker_entered.set()
        assert worker_release.wait(timeout=2.0)
        with counter_lock:
            active_workers -= 1
        return False

    monkeypatch.setattr(detector, "_reload_config", blocked_first_reload)
    monkeypatch.setattr(detector, "cache_monitor_geometry", lambda: None)
    detector._check_edge = blocked_check
    for name in (
        "_flow_server",
        "_logi_flow_server",
        "_logi_discovery",
        "_presence_server",
        "_handoff_manager",
        "_juhflow_bridge",
        "_flow_indicator",
    ):
        monkeypatch.setattr(flow_module, name, None)
    monkeypatch.setattr(flow_module, "_edge_detector", detector)

    starter = threading.Thread(target=detector.start)
    try:
        starter.start()
        assert first_config_entered.wait(timeout=1.0)

        # The bounded stop invalidates the blocked reservation but retains its
        # owner because that reservation has not yet cleared.
        started = time.monotonic()
        flow_module.stop_flow_server()
        assert time.monotonic() - started < 0.75
        assert flow_module.get_edge_detector() is detector

        # A restart requested after stop returns must survive until the stale
        # config load clears. Concurrent requests coalesce and must not publish
        # before that release.
        detector.start()
        detector.start()
        assert config_loads == 1
        assert not worker_entered.is_set()

        first_config_release.set()
        starter.join(timeout=1.0)
        assert not starter.is_alive()
        assert replacement_config_loaded.wait(timeout=1.0)
        assert worker_entered.wait(timeout=1.0)

        with counter_lock:
            assert config_loads == 2
            assert worker_calls == 1
            assert max_active_workers == 1
        assert flow_module.get_edge_detector() is detector
        assert detector._active_generation == detector._generation
    finally:
        first_config_release.set()
        worker_release.set()
        starter.join(timeout=1.0)
        detector.stop()
        thread = detector._thread
        if thread is not None:
            thread.join(timeout=1.0)


def test_stop_fences_a_blocked_edge_check_before_handoff_teardown(monkeypatch):
    detector = ScreenEdgeDetector()
    detector._enabled = True
    detector._extend_edge_zone = True
    detector._flow_direction = "right"
    detector._prev_pos = (0, 500)
    detector._prev_time = time.monotonic()
    monkeypatch.setattr(detector, "_reload_config", lambda: None)
    monkeypatch.setattr(detector, "cache_monitor_geometry", lambda: None)

    cursor_entered = threading.Event()
    cursor_release = threading.Event()
    hits = []

    cursor_module = ModuleType("overlay_cursor")

    def blocked_cursor_pos():
        cursor_entered.set()
        assert cursor_release.wait(timeout=2.0)
        return (1_999_995, 500)

    setattr(cursor_module, "get_cursor_pos", blocked_cursor_pos)
    setattr(
        cursor_module,
        "get_screen_geometry",
        lambda cursor_pos=None: {
            "x": 0,
            "y": 0,
            "width": 2_000_000,
            "height": 1000,
        },
    )
    monkeypatch.setitem(sys.modules, "overlay_cursor", cursor_module)
    monkeypatch.setitem(sys.modules, "overlay.overlay_cursor", cursor_module)

    class _HandoffManager:
        def __init__(self):
            self.stopped = False

        def on_edge_hit(self, *args):
            hits.append((self.stopped, args))

        def stop(self):
            self.stopped = True

    handoff = _HandoffManager()
    detector.on_edge_hit = handoff.on_edge_hit
    for name in (
        "_flow_server",
        "_logi_flow_server",
        "_logi_discovery",
        "_presence_server",
        "_juhflow_bridge",
        "_flow_indicator",
    ):
        monkeypatch.setattr(flow_module, name, None)
    monkeypatch.setattr(flow_module, "_edge_detector", detector)
    monkeypatch.setattr(flow_module, "_handoff_manager", handoff)

    try:
        detector.start()
        assert cursor_entered.wait(timeout=1.0)
        poll_thread = detector._thread

        started = time.monotonic()
        flow_module.stop_flow_server()
        assert time.monotonic() - started < 0.75
        assert poll_thread.is_alive()
        assert flow_module.get_edge_detector() is detector
        assert flow_module.get_handoff_manager() is handoff
        assert handoff.stopped is False

        cursor_release.set()
        poll_thread.join(timeout=1.0)
        assert not poll_thread.is_alive()
        assert hits == []

        flow_module.stop_flow_server()
        assert flow_module.get_edge_detector() is None
        assert flow_module.get_handoff_manager() is None
        assert handoff.stopped is True
    finally:
        cursor_release.set()
        detector.stop()
        thread = detector._thread
        if thread is not None:
            thread.join(timeout=1.0)


def test_stop_deadline_retains_handoff_during_a_blocked_callback(monkeypatch):
    detector = ScreenEdgeDetector()
    detector._enabled = True
    monkeypatch.setattr(detector, "_reload_config", lambda: None)
    monkeypatch.setattr(detector, "cache_monitor_geometry", lambda: None)

    callback_entered = threading.Event()
    callback_release = threading.Event()
    callback_finished = threading.Event()
    callback_observations = []

    class _HandoffManager:
        def __init__(self):
            self.stopped = False

        def on_edge_hit(self, *args):
            callback_entered.set()
            callback_release.wait(timeout=2.0)
            callback_observations.append((self.stopped, args))
            callback_finished.set()

        def stop(self):
            self.stopped = True

    handoff = _HandoffManager()
    detector.on_edge_hit = handoff.on_edge_hit

    dispatched = False

    def dispatch_once(generation=None):
        nonlocal dispatched
        if not dispatched:
            dispatched = True
            detector._dispatch_edge_hit(
                generation,
                "right",
                995,
                500,
                {"x": 0, "y": 0, "width": 1000, "height": 1000},
            )
        return False

    detector._check_edge = dispatch_once
    for name in (
        "_flow_server",
        "_logi_flow_server",
        "_logi_discovery",
        "_presence_server",
        "_juhflow_bridge",
        "_flow_indicator",
    ):
        monkeypatch.setattr(flow_module, name, None)
    monkeypatch.setattr(flow_module, "_edge_detector", detector)
    monkeypatch.setattr(flow_module, "_handoff_manager", handoff)

    try:
        detector.start()
        assert callback_entered.wait(timeout=1.0)
        poll_thread = detector._thread

        started = time.monotonic()
        flow_module.stop_flow_server()
        elapsed = time.monotonic() - started

        assert 0.15 <= elapsed < 0.75
        assert poll_thread.is_alive()
        assert flow_module.get_edge_detector() is detector
        assert flow_module.get_handoff_manager() is handoff
        assert handoff.stopped is False

        callback_release.set()
        assert callback_finished.wait(timeout=1.0)
        poll_thread.join(timeout=1.0)
        assert not poll_thread.is_alive()
        assert callback_observations == [(False, (
            "right",
            995,
            500,
            {"x": 0, "y": 0, "width": 1000, "height": 1000},
        ))]

        flow_module.stop_flow_server()
        assert flow_module.get_edge_detector() is None
        assert flow_module.get_handoff_manager() is None
        assert handoff.stopped is True
    finally:
        callback_release.set()
        detector.stop()
        thread = detector._thread
        if thread is not None:
            thread.join(timeout=1.0)


def test_retained_callback_dependency_graph_survives_stop_and_restart(
    monkeypatch, tmp_path
):
    """A bounded stop retains every dependency of a real handoff callback."""
    config_dir = tmp_path / ".config" / "juhradial"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.json"
    config_path.write_text('{"flow": {"edge_trigger": true}}')
    monkeypatch.setenv("HOME", os.fspath(tmp_path))

    detector = ScreenEdgeDetector()
    monkeypatch.setattr(detector, "_reload_config", lambda: None)
    monkeypatch.setattr(detector, "cache_monitor_geometry", lambda: None)

    callback_armed = threading.Event()
    callback_entered = threading.Event()
    callback_release = threading.Event()
    callback_finished = threading.Event()
    observations = []
    teardown = []
    dispatched = False

    def dispatch_once(generation=None):
        nonlocal dispatched
        assert callback_armed.wait(timeout=2.0)
        if not dispatched:
            dispatched = True
            detector._dispatch_edge_hit(
                generation,
                "right",
                995,
                500,
                {"x": 0, "y": 0, "width": 1000, "height": 1000},
            )
        return False

    detector._check_edge = dispatch_once

    class _Service:
        def __init__(self, *args, **kwargs):
            self.started = False
            self.stopped = False
            self.start_calls = 0
            self.stop_calls = 0
            self.on_message = None

        def start(self):
            self.started = True
            self.start_calls += 1

        def stop(self):
            self.stopped = True
            self.stop_calls += 1

        def add_peer_key(self, *args):
            pass

    class _Presence(_Service):
        instances = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.instances.append(self)

        def stop(self):
            teardown.append("presence")
            super().stop()

        def send_to_peer(self, peer_name, message):
            observations.append((
                "presence",
                self.stopped,
                self.on_message.__self__,
                peer_name,
                message["type"],
            ))
            return True

    class _Bridge(_Service):
        instances = []

        def __init__(self, on_edge_hit=None, on_clipboard=None, **kwargs):
            super().__init__(**kwargs)
            self.instances.append(self)
            self.on_edge_hit = on_edge_hit
            self.on_clipboard = on_clipboard

        def stop(self):
            teardown.append("bridge")
            super().stop()

        def get_peers(self):
            return {"bridge-peer": object()}

        def send_edge_hit(self, edge, position, screen, relative_position=None):
            observations.append((
                "bridge",
                self.stopped,
                edge,
                position,
                relative_position,
            ))

    class _Indicator:
        def configure(self, direction):
            pass

        def hide(self):
            pass

        def deleteLater(self):
            pass

    keys_module = ModuleType("flow.keys")
    keys_module.generate_identity = lambda: (object(), b"public", b"node")
    keys_module.get_all_peers = lambda: {}
    bridge_module = ModuleType("flow.juhflow_bridge")
    bridge_module.JuhFlowBridge = _Bridge
    indicator_module = ModuleType("flow.indicator")
    indicator_module.FlowEdgeIndicator = _Indicator
    monkeypatch.setitem(sys.modules, "flow.keys", keys_module)
    monkeypatch.setitem(sys.modules, "flow.juhflow_bridge", bridge_module)
    monkeypatch.setitem(sys.modules, "flow.indicator", indicator_module)
    monkeypatch.setattr(edge_module, "ScreenEdgeDetector", lambda: detector)
    monkeypatch.setattr(flow_module, "FlowServer", _Service)
    monkeypatch.setattr(flow_module, "LogiFlowServer", _Service)
    monkeypatch.setattr(flow_module, "FlowPresenceServer", _Presence)
    monkeypatch.setattr(flow_module, "LogiFlowDiscoveryResponder", _Service)

    from flow import handoff as handoff_module

    monkeypatch.setattr(handoff_module, "_CFG_PATH", config_path)
    for name in (
        "_flow_server",
        "_logi_flow_server",
        "_logi_discovery",
        "_presence_server",
        "_handoff_manager",
        "_edge_detector",
        "_juhflow_bridge",
        "_flow_indicator",
    ):
        monkeypatch.setattr(flow_module, name, None)

    manager = None
    presence = None
    bridge = None
    callback_thread = None
    try:
        flow_module.start_flow_server()
        manager = flow_module.get_handoff_manager()
        presence = flow_module.get_presence_server()
        bridge = flow_module.get_juhflow_bridge()
        manager.set_peer_edge("presence-peer", "right")
        monkeypatch.setattr(manager, "_sync_clipboard", lambda _peer: None)

        manager_stop = manager.stop

        def counted_manager_stop():
            teardown.append("manager")
            manager_stop()

        monkeypatch.setattr(manager, "stop", counted_manager_stop)

        config_calls = 0

        def blocked_flow_config():
            nonlocal config_calls
            config_calls += 1
            if config_calls == 1:
                callback_entered.set()
                assert callback_release.wait(timeout=2.0)
                callback_finished.set()
            return {"direction": "right"}

        monkeypatch.setattr(manager, "get_flow_config", blocked_flow_config)
        callback_armed.set()
        assert callback_entered.wait(timeout=1.0)
        callback_thread = detector._thread

        started = time.monotonic()
        flow_module.stop_flow_server()
        elapsed = time.monotonic() - started

        assert 0.15 <= elapsed < 0.75
        assert callback_thread.is_alive()
        assert flow_module.get_edge_detector() is detector
        assert flow_module.get_handoff_manager() is manager
        assert flow_module.get_presence_server() is presence
        assert flow_module.get_juhflow_bridge() is bridge
        assert manager.presence_server is presence
        assert manager.juhflow_bridge is bridge
        assert presence.on_message.__self__ is manager
        assert teardown == []
        assert manager.presence_clients == {}
        assert presence.stop_calls == 0
        assert bridge.stop_calls == 0

        callback_release.set()
        assert callback_finished.wait(timeout=1.0)
        callback_thread.join(timeout=1.0)
        assert not callback_thread.is_alive()
        assert observations == [
            ("presence", False, manager, "presence-peer", "cursor_handoff"),
            ("bridge", False, "right", (995, 500), 0.5),
        ]

        config_path.write_text('{"flow": {"edge_trigger": false}}')
        flow_module.start_flow_server()

        assert flow_module.get_edge_detector() is detector
        assert flow_module.get_handoff_manager() is manager
        assert flow_module.get_presence_server() is presence
        assert flow_module.get_juhflow_bridge() is bridge
        assert manager.presence_server is presence
        assert manager.juhflow_bridge is bridge
        assert presence.on_message.__self__ is manager
        assert detector.on_edge_hit.__self__ is manager
        assert len(_Presence.instances) == 1
        assert len(_Bridge.instances) == 1
        assert detector._enabled is False
        assert detector._thread is not callback_thread

        flow_module.stop_flow_server()

        assert flow_module.get_edge_detector() is None
        assert flow_module.get_handoff_manager() is None
        assert flow_module.get_presence_server() is None
        assert flow_module.get_juhflow_bridge() is None
        assert teardown == ["manager", "bridge", "presence"]
        assert presence.stop_calls == 1
        assert bridge.stop_calls == 1
    finally:
        callback_armed.set()
        callback_release.set()
        flow_module.stop_flow_server()
        detector.stop()
        thread = detector._thread
        if thread is not None:
            thread.join(timeout=1.0)


def test_callback_can_stop_reentrantly_without_claiming_quiescence(monkeypatch):
    detector = ScreenEdgeDetector()
    detector._enabled = True
    monkeypatch.setattr(detector, "_reload_config", lambda: None)
    monkeypatch.setattr(detector, "cache_monitor_geometry", lambda: None)

    callback_finished = threading.Event()
    stop_results = []

    def on_edge_hit(*_args):
        started = time.monotonic()
        stop_results.append((detector.stop(), time.monotonic() - started))
        callback_finished.set()

    detector.on_edge_hit = on_edge_hit
    dispatched = False

    def dispatch_once(generation=None):
        nonlocal dispatched
        if not dispatched:
            dispatched = True
            detector._dispatch_edge_hit(
                generation,
                "right",
                995,
                500,
                {"x": 0, "y": 0, "width": 1000, "height": 1000},
            )
        return False

    detector._check_edge = dispatch_once

    detector.start()
    assert callback_finished.wait(timeout=1.0)
    poll_thread = detector._thread
    poll_thread.join(timeout=1.0)

    assert not poll_thread.is_alive()
    assert stop_results[0][0] is False
    assert stop_results[0][1] < 0.5
    assert detector.stop() is True


def test_stop_restart_never_overlaps_or_orphans_a_blocked_poll_thread(monkeypatch):
    detector = ScreenEdgeDetector()
    detector._enabled = True
    monkeypatch.setattr(detector, "_reload_config", lambda: None)
    monkeypatch.setattr(detector, "cache_monitor_geometry", lambda: None)

    first_entered = threading.Event()
    first_release = threading.Event()
    replacement_entered = threading.Event()
    replacement_release = threading.Event()
    counter_lock = threading.Lock()
    active = 0
    max_active = 0
    calls = 0

    def blocked_check(_generation=None):
        nonlocal active, max_active, calls
        with counter_lock:
            calls += 1
            call = calls
            active += 1
            max_active = max(max_active, active)
        entered = first_entered if call == 1 else replacement_entered
        release = first_release if call == 1 else replacement_release
        entered.set()
        release.wait(timeout=2.0)
        with counter_lock:
            active -= 1
        return False

    detector._check_edge = blocked_check
    for name in (
        "_flow_server",
        "_logi_flow_server",
        "_logi_discovery",
        "_presence_server",
        "_handoff_manager",
        "_juhflow_bridge",
        "_flow_indicator",
    ):
        monkeypatch.setattr(flow_module, name, None)
    monkeypatch.setattr(flow_module, "_edge_detector", detector)

    try:
        detector.start()
        assert first_entered.wait(timeout=1.0)
        first_thread = detector._thread

        # stop_flow_server must return promptly, but it must retain ownership
        # while the real poll thread remains blocked beyond the 200 ms join.
        started = time.monotonic()
        flow_module.stop_flow_server()
        assert time.monotonic() - started < 0.75
        assert flow_module.get_edge_detector() is detector
        assert first_thread.is_alive()

        # This is the detector.start() performed by the next Flow startup. It
        # records a pending restart rather than creating an overlapping thread.
        detector.start()
        time.sleep(0.05)
        assert calls == 1

        first_release.set()
        assert replacement_entered.wait(timeout=1.0)
        replacement_thread = detector._thread
        assert replacement_thread is not first_thread
        assert not first_thread.is_alive()
        first_thread.join(timeout=1.0)
        assert max_active == 1

        replacement_release.set()
        assert detector.stop() is True
        assert detector._thread is None
        assert not replacement_thread.is_alive()
    finally:
        first_release.set()
        replacement_release.set()
        detector.stop()
        thread = detector._thread
        if thread is not None:
            thread.join(timeout=1.0)


def test_restart_resets_state_written_by_a_terminal_old_edge_check(monkeypatch):
    detector = ScreenEdgeDetector()
    detector._enabled = True
    detector._extend_edge_zone = True
    detector._flow_direction = "right"
    monkeypatch.setattr(detector, "_reload_config", lambda: None)
    monkeypatch.setattr(detector, "cache_monitor_geometry", lambda: None)
    monkeypatch.setattr(edge_module, "EDGE_DWELL_MS", 0)
    monkeypatch.setattr(edge_module, "EDGE_VELOCITY_INSTANT_PX_PER_S", 0.000001)

    cursor_entered = threading.Event()
    cursor_release = threading.Event()
    old_state_written = threading.Event()
    old_return_release = threading.Event()
    replacement_sampled = threading.Event()
    replacement_return_release = threading.Event()
    call_lock = threading.Lock()
    cursor_calls = 0
    check_calls = 0
    hits = []
    old_state = {}
    replacement_state = {}

    cursor_module = ModuleType("overlay_cursor")

    def get_cursor_pos():
        nonlocal cursor_calls
        with call_lock:
            cursor_calls += 1
            call = cursor_calls
        if call == 1:
            cursor_entered.set()
            cursor_release.wait(timeout=2.0)
            return (995, 500)
        return (996, 500)

    setattr(cursor_module, "get_cursor_pos", get_cursor_pos)
    setattr(
        cursor_module,
        "get_screen_geometry",
        lambda cursor_pos=None: {
            "x": 0,
            "y": 0,
            "width": 1000,
            "height": 1000,
        },
    )
    monkeypatch.setitem(sys.modules, "overlay_cursor", cursor_module)
    monkeypatch.setitem(sys.modules, "overlay.overlay_cursor", cursor_module)
    detector.on_edge_hit = lambda *args: hits.append(args)

    real_check_edge = detector._check_edge

    def observed_check(generation=None):
        nonlocal check_calls
        with call_lock:
            check_calls += 1
            call = check_calls
        result = real_check_edge(generation)
        state = {
            "dwell_start": detector._dwell_start,
            "dwell_edge": detector._dwell_edge,
            "prev_pos": detector._prev_pos,
            "prev_time": detector._prev_time,
            "last_fire_time": detector._last_fire_time,
            "result": result,
        }
        if call == 1:
            old_state.update(state)
            old_state_written.set()
            old_return_release.wait(timeout=2.0)
        else:
            replacement_state.update(state)
            replacement_sampled.set()
            replacement_return_release.wait(timeout=2.0)
        return result

    detector._check_edge = observed_check

    try:
        detector.start()
        assert cursor_entered.wait(timeout=1.0)
        first_thread = detector._thread

        # The old sample passed cooldown before blocking. Seed an otherwise
        # expired generation-local cooldown while it is blocked so restart must
        # clear that state as well as dwell and velocity history.
        assert detector.stop() is False
        stale_fire_time = time.monotonic() - 10.0
        detector._last_fire_time = stale_fire_time
        detector.start()

        cursor_release.set()
        assert old_state_written.wait(timeout=1.0)
        assert old_state["dwell_edge"] == "right"
        assert old_state["dwell_start"] is not None
        assert old_state["prev_pos"] == (995, 500)
        assert old_state["prev_time"] > 0
        assert old_state["last_fire_time"] == stale_fire_time
        assert old_state["result"] is True

        old_return_release.set()
        assert replacement_sampled.wait(timeout=1.0)
        replacement_thread = detector._thread
        assert replacement_thread is not first_thread
        assert not first_thread.is_alive()

        # A replacement's first real sample establishes new dwell/velocity
        # state. It must neither inherit enough dwell nor derive slam velocity
        # from the terminal generation, and stale cooldown must be gone.
        assert hits == []
        assert replacement_state["result"] is True
        assert replacement_state["dwell_edge"] == "right"
        assert replacement_state["dwell_start"] is not None
        assert replacement_state["prev_pos"] == (996, 500)
        assert replacement_state["prev_time"] > old_state["prev_time"]
        assert replacement_state["last_fire_time"] == 0.0
    finally:
        cursor_release.set()
        old_return_release.set()
        replacement_return_release.set()
        detector.stop()
        thread = detector._thread
        if thread is not None:
            thread.join(timeout=1.0)


def test_retained_production_owner_applies_disabled_edge_config_on_restart(
    monkeypatch, tmp_path
):
    config_dir = tmp_path / ".config" / "juhradial"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.json"
    config_path.write_text('{"flow": {"edge_trigger": true}}')
    monkeypatch.setenv("HOME", os.fspath(tmp_path))

    detector = ScreenEdgeDetector()
    monkeypatch.setattr(detector, "_reload_config", lambda: None)
    monkeypatch.setattr(detector, "cache_monitor_geometry", lambda: None)

    class _RecordingEvent:
        def __init__(self):
            self.event = threading.Event()
            self.indefinite_wait = threading.Event()

        def wait(self, timeout=None):
            if timeout is None:
                self.indefinite_wait.set()
            return self.event.wait(timeout)

        def set(self):
            self.event.set()

        def clear(self):
            self.event.clear()

    wake = _RecordingEvent()
    detector._wake_event = wake
    first_check_entered = threading.Event()
    first_check_release = threading.Event()
    unexpected_check = threading.Event()
    check_lock = threading.Lock()
    check_calls = 0
    hits = []

    def blocked_check(generation=None):
        nonlocal check_calls
        with check_lock:
            check_calls += 1
            call = check_calls
        if call == 1:
            first_check_entered.set()
            first_check_release.wait(timeout=2.0)
        else:
            unexpected_check.set()
            detector._dispatch_edge_hit(
                generation,
                "right",
                995,
                500,
                {"x": 0, "y": 0, "width": 1000, "height": 1000},
            )
        return False

    detector._check_edge = blocked_check

    class _Service:
        def __init__(self, *args, **kwargs):
            self.stopped = False
            self.on_message = None

        def start(self):
            pass

        def stop(self):
            self.stopped = True

        def add_peer_key(self, *args):
            pass

    class _HandoffManager:
        def __init__(self, edge_detector=None, presence_server=None):
            self.edge_detector = edge_detector
            self.presence_server = presence_server
            self.juhflow_bridge = None
            self.stopped = False
            if edge_detector is not None:
                edge_detector.on_edge_hit = self.on_edge_hit

        def on_edge_hit(self, *args):
            hits.append(args)

        def cache_flow_monitor_geometry(self):
            pass

        def connect_to_peer(self, *args):
            pass

        def stop(self):
            self.stopped = True

    class _Bridge(_Service):
        pass

    class _Indicator:
        def configure(self, direction):
            pass

        def hide(self):
            pass

        def deleteLater(self):
            pass

    keys_module = ModuleType("flow.keys")
    keys_module.generate_identity = lambda: (object(), b"public", b"node")
    keys_module.get_all_peers = lambda: {}
    handoff_module = ModuleType("flow.handoff")
    handoff_module.FlowHandoffManager = _HandoffManager
    bridge_module = ModuleType("flow.juhflow_bridge")
    bridge_module.JuhFlowBridge = _Bridge
    indicator_module = ModuleType("flow.indicator")
    indicator_module.FlowEdgeIndicator = _Indicator
    monkeypatch.setitem(sys.modules, "flow.keys", keys_module)
    monkeypatch.setitem(sys.modules, "flow.handoff", handoff_module)
    monkeypatch.setitem(sys.modules, "flow.juhflow_bridge", bridge_module)
    monkeypatch.setitem(sys.modules, "flow.indicator", indicator_module)
    monkeypatch.setattr(edge_module, "ScreenEdgeDetector", lambda: detector)
    monkeypatch.setattr(flow_module, "FlowServer", _Service)
    monkeypatch.setattr(flow_module, "LogiFlowServer", _Service)
    monkeypatch.setattr(flow_module, "FlowPresenceServer", _Service)
    monkeypatch.setattr(flow_module, "LogiFlowDiscoveryResponder", _Service)

    for name in (
        "_flow_server",
        "_logi_flow_server",
        "_logi_discovery",
        "_presence_server",
        "_handoff_manager",
        "_edge_detector",
        "_juhflow_bridge",
        "_flow_indicator",
    ):
        monkeypatch.setattr(flow_module, name, None)

    manager = None
    try:
        flow_module.start_flow_server()
        assert first_check_entered.wait(timeout=1.0)
        first_thread = detector._thread
        manager = flow_module.get_handoff_manager()
        assert detector._enabled is True

        started = time.monotonic()
        flow_module.stop_flow_server()
        assert time.monotonic() - started < 0.75
        assert flow_module.get_edge_detector() is detector
        assert flow_module.get_handoff_manager() is manager
        assert manager.stopped is False

        config_path.write_text('{"flow": {"edge_trigger": false}}')
        flow_module.start_flow_server()
        first_check_release.set()

        assert _wait_until(
            lambda: wake.indefinite_wait.is_set() or unexpected_check.is_set()
        )
        assert detector._thread is not first_thread
        assert not first_thread.is_alive()
        assert detector._enabled is False
        assert wake.indefinite_wait.is_set()
        assert not unexpected_check.is_set()
        assert check_calls == 1
        assert hits == []

        flow_module.stop_flow_server()
        assert flow_module.get_edge_detector() is None
        assert flow_module.get_handoff_manager() is None
        assert manager.stopped is True
    finally:
        first_check_release.set()
        flow_module.stop_flow_server()
        detector.stop()
        thread = detector._thread
        if thread is not None:
            thread.join(timeout=1.0)


def _install_cursor(monkeypatch, positions, screen=None):
    samples = iter(positions)
    cursor_module = ModuleType("overlay_cursor")
    setattr(cursor_module, "get_cursor_pos", lambda: next(samples))
    setattr(
        cursor_module,
        "get_screen_geometry",
        lambda cursor_pos=None: screen
        or {"x": 0, "y": 0, "width": 1000, "height": 1000},
    )
    monkeypatch.setitem(sys.modules, "overlay_cursor", cursor_module)
    monkeypatch.setitem(sys.modules, "overlay.overlay_cursor", cursor_module)


def test_edge_check_reports_far_and_near_polling_zones(monkeypatch):
    detector = ScreenEdgeDetector()
    detector._extend_edge_zone = True
    detector._flow_direction = "right"
    monkeypatch.setattr(edge_module.time, "monotonic", lambda: 100.0)
    _install_cursor(monkeypatch, [(500, 500), (950, 500), (995, 500)])

    assert detector._check_edge() is False
    assert detector._check_edge() is True
    assert detector._check_edge() is True


def test_existing_dwell_threshold_still_fires(monkeypatch):
    detector = ScreenEdgeDetector()
    detector._extend_edge_zone = True
    detector._flow_direction = "right"
    hits = []
    detector.on_edge_hit = lambda *args: hits.append(args)
    clock = iter([100.0, 100.4])
    monkeypatch.setattr(edge_module.time, "monotonic", lambda: next(clock))
    _install_cursor(monkeypatch, [(995, 500), (995, 500)])

    assert detector._check_edge() is True
    assert detector._check_edge() is False
    assert len(hits) == 1
    assert hits[0][0] == "right"


def test_existing_fast_slam_still_fires_immediately(monkeypatch):
    detector = ScreenEdgeDetector()
    detector._extend_edge_zone = True
    detector._flow_direction = "right"
    hits = []
    detector.on_edge_hit = lambda *args: hits.append(args)
    clock = iter([100.0, 100.01])
    monkeypatch.setattr(edge_module.time, "monotonic", lambda: next(clock))
    _install_cursor(monkeypatch, [(500, 500), (995, 500)])

    assert detector._check_edge() is False
    assert detector._check_edge() is False
    assert len(hits) == 1
    assert hits[0][0] == "right"
