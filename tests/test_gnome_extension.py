#!/usr/bin/env python3
"""The GNOME cursor helper declares every Shell release it runs on (#144).

GNOME Shell marks an extension OUT_OF_DATE, and never loads it, when no entry
of metadata.json's shell-version starts with the running major version
(js/ui/extensionSystem.js _isOutOfDate). Keep the list contiguous from 45
(the ESM extension format this file uses) through the newest supported release.
"""

import json
import re
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "gnome-extension" / "juhradial-cursor@dev.juhlabs.com"
NEWEST_SUPPORTED = 51


def test_shell_versions_are_contiguous_through_the_newest_release():
    meta = json.loads((EXT / "metadata.json").read_text(encoding="utf-8"))
    versions = meta["shell-version"]
    assert all(isinstance(v, str) for v in versions), "GNOME compares strings"
    assert [int(v) for v in versions] == list(range(45, NEWEST_SUPPORTED + 1))
    assert meta["uuid"] == EXT.name


def test_extension_uses_the_esm_default_export_and_a_sync_disable():
    src = (EXT / "extension.js").read_text(encoding="utf-8")
    assert "export default class" in src
    # GNOME 51 throws when disable() is async.
    assert not re.search(r"async\s+disable\s*\(", src)
    assert "global.get_pointer()" in src
