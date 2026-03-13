#!/usr/bin/env python3
"""
JuhRadial MX - Macro Storage

File I/O for macro definitions. Each macro is stored as a separate
JSON file in ~/.config/juhradial/macros/<uuid>.json.

Atomic writes (tmp + os.replace) to prevent corruption.

SPDX-License-Identifier: GPL-3.0
"""

import copy
import json
import logging
import os
import re
import subprocess
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

MACROS_DIR_NAME = "macros"
CONFIG_DIR = Path.home() / ".config" / "juhradial"


def get_macros_dir() -> Path:
    """Return the macros directory path."""
    return CONFIG_DIR / MACROS_DIR_NAME


def ensure_macros_dir() -> Path:
    """Create macros directory if it does not exist. Returns the path."""
    macros_dir = get_macros_dir()
    macros_dir.mkdir(parents=True, exist_ok=True)
    return macros_dir


def new_macro_template() -> dict:
    """Return a blank macro dict with sensible defaults."""
    return {
        "id": str(uuid.uuid4()),
        "name": "New Macro",
        "description": "",
        "repeat_mode": "once",      # once | while_holding | toggle | repeat_n | sequence
        "repeat_count": 3,           # only used when repeat_mode == repeat_n
        "use_standard_delay": True,
        "standard_delay_ms": 50,
        "actions": [],               # list of action dicts (see below)
        "assigned_trigger": None,    # button id or None
    }


def new_action(action_type, **kwargs) -> dict:
    """Create a new action dict.

    Supported action_type values:
        key_down   - {"key": "a", "keycode": 38}
        key_up     - {"key": "a", "keycode": 38}
        mouse_down - {"button": "left"}
        mouse_up   - {"button": "left"}
        mouse_click- {"button": "left"}
        delay      - {"ms": 50}
        text       - {"text": "hello"}
        scroll     - {"direction": "up", "amount": 3}
    """
    action = {"type": action_type, "id": str(uuid.uuid4())}
    action.update(kwargs)
    # Ensure delay field exists for timeline display
    if "delay_after_ms" not in action:
        action["delay_after_ms"] = 0
    return action


def load_all_macros() -> list:
    """Load all macro files from the macros directory.

    Returns a list of macro dicts, sorted by name.
    """
    macros_dir = get_macros_dir()
    if not macros_dir.exists():
        return []

    macros = []
    for path in macros_dir.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                macro = json.load(f)
            # Ensure id matches filename stem
            macro.setdefault("id", path.stem)
            macros.append(macro)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load macro %s: %s", path.name, e)

    macros.sort(key=lambda m: m.get("name", "").lower())
    return macros


def load_macro(macro_id: str) -> dict | None:
    """Load a single macro by its id. Returns None if not found."""
    path = get_macros_dir() / f"{macro_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load macro %s: %s", macro_id, e)
        return None


_VALID_ID_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _validate_id(macro_id: str) -> bool:
    """Validate macro ID is safe for file paths (no path traversal)."""
    return bool(macro_id and _VALID_ID_RE.match(macro_id))


def _reload_daemon_triggers():
    """Tell the daemon to reload macro trigger bindings via D-Bus."""
    try:
        subprocess.Popen(
            [
                "dbus-send", "--session", "--type=method_call",
                "--dest=org.kde.juhradialmx",
                "/org/kde/juhradialmx/Daemon",
                "org.kde.juhradialmx.Daemon.ReloadMacroTriggers",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.debug("dbus-send not found, daemon trigger reload skipped")
    except OSError as e:
        logger.debug("Failed to reload daemon triggers: %s", e)


def save_macro(macro: dict) -> bool:
    """Save a macro dict to disk atomically.

    The macro dict must contain an 'id' field.
    Returns True on success. Also notifies the daemon to reload triggers.
    """
    macro_id = macro.get("id")
    if not macro_id or not _validate_id(macro_id):
        logger.error("Cannot save macro: missing or invalid 'id' field: %s", macro_id)
        return False

    macros_dir = ensure_macros_dir()
    target = macros_dir / f"{macro_id}.json"
    tmp_path = target.with_suffix(".json.tmp")

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(macro, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, target)
        logger.info("Saved macro '%s' (%s)", macro.get("name", ""), macro_id)
        _reload_daemon_triggers()
        return True
    except OSError as e:
        logger.error("Failed to save macro %s: %s", macro_id, e)
        # Clean up temp file if it exists
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as cleanup_err:
            logger.debug("Temp file cleanup failed: %s", cleanup_err)
        return False


def delete_macro(macro_id: str) -> bool:
    """Delete a macro file by its id. Returns True on success."""
    path = get_macros_dir() / f"{macro_id}.json"
    try:
        path.unlink(missing_ok=True)
        logger.info("Deleted macro %s", macro_id)
        _reload_daemon_triggers()
        return True
    except OSError as e:
        logger.error("Failed to delete macro %s: %s", macro_id, e)
        return False


def duplicate_macro(macro_id: str) -> dict | None:
    """Duplicate an existing macro with a new id. Returns the new macro dict."""
    original = load_macro(macro_id)
    if original is None:
        return None

    new = copy.deepcopy(original)
    new["id"] = str(uuid.uuid4())
    new["name"] = f"{original.get('name', 'Macro')} (Copy)"
    new["assigned_trigger"] = None  # Don't duplicate trigger binding

    if save_macro(new):
        return new
    return None


# Repeat mode display helpers
REPEAT_MODE_LABELS = {
    "once": "Once",
    "while_holding": "While Holding",
    "toggle": "Toggle On/Off",
    "repeat_n": "Repeat N Times",
    "sequence": "Sequence",
}

REPEAT_MODE_ICONS = {
    "once": "media-playback-start-symbolic",
    "while_holding": "input-mouse-symbolic",
    "toggle": "media-playlist-repeat-symbolic",
    "repeat_n": "view-list-ordered-symbolic",
    "sequence": "view-list-symbolic",
}

ACTION_TYPE_ICONS = {
    "key_down": "go-down-symbolic",
    "key_up": "go-up-symbolic",
    "mouse_down": "input-mouse-symbolic",
    "mouse_up": "input-mouse-symbolic",
    "mouse_click": "input-mouse-symbolic",
    "delay": "preferences-system-time-symbolic",
    "text": "insert-text-symbolic",
    "scroll": "input-touchpad-symbolic",
}
