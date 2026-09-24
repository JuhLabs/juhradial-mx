"""Test-wide setup: the suite asserts English UI text.

The settings app translates from the desktop locale when config.json names no
language, and complete catalogs ship for 18 languages, so a developer on a
non-English desktop would otherwise see translated strings in assertions.
"""
import os
import sys

import pytest

os.environ["LANGUAGE"] = "en"


def pytest_configure(config):
    # PyGObject 3.56 reads its own deprecated GLib.unix_signal_add_full alias
    # while it loads the GLib overrides (gi/overrides/__init__.py), on every
    # import of gi; no project code calls it.
    config.addinivalue_line(
        "filterwarnings",
        "ignore:GLib.unix_signal_add_full is deprecated:DeprecationWarning",
    )


@pytest.fixture(autouse=True)
def _backend_timers_end_with_their_test(monkeypatch):
    """One-shot timers the settings backend starts (a device refresh, the
    update check, a toast) run only within the test that started them. Tests
    make many Backends; a timer from an earlier test firing in a later test's
    event loop touched objects that were gone (a crash on Qt 6.4)."""
    backend = sys.modules.get("bridge.backend")
    if backend is None:
        yield
        return
    live = [True]

    class _Timer(backend.QTimer):
        @staticmethod
        def singleShot(msec, *args):
            *rest, fn = args
            _Timer._real(msec, *rest, lambda *a: fn(*a) if live[0] else None)

    _Timer._real = backend.QTimer.singleShot
    monkeypatch.setattr(backend, "QTimer", _Timer)
    yield
    live[0] = False
