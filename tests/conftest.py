"""Test-wide setup: the suite asserts English UI text.

The settings app translates from the desktop locale when config.json names no
language, and complete catalogs ship for 18 languages, so a developer on a
non-English desktop would otherwise see translated strings in assertions.
"""
import os

os.environ["LANGUAGE"] = "en"


def pytest_configure(config):
    # PyGObject 3.56 reads its own deprecated GLib.unix_signal_add_full alias
    # while it loads the GLib overrides (gi/overrides/__init__.py), on every
    # import of gi; no project code calls it.
    config.addinivalue_line(
        "filterwarnings",
        "ignore:GLib.unix_signal_add_full is deprecated:DeprecationWarning",
    )
