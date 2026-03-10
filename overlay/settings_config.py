#!/usr/bin/env python3
"""
JuhRadial MX - Configuration Manager

Manages config.json for the settings dashboard and daemon.
Provides atomic saves, D-Bus notification, and device detection.

SPDX-License-Identifier: GPL-3.0
"""

import os
import json
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gio, GLib

from i18n import _


# =============================================================================
# CONFIGURATION MANAGER
# =============================================================================
class ConfigManager:
    """Manages JuhRadial MX configuration - shares config with daemon"""

    CONFIG_DIR = Path.home() / ".config" / "juhradial"
    CONFIG_FILE = CONFIG_DIR / "config.json"

    DEFAULT_CONFIG = {
        "haptics": {
            "enabled": True,
            "default_pattern": "subtle_collision",
            "per_event": {
                "menu_appear": "damp_state_change",
                "slice_change": "subtle_collision",
                "confirm": "sharp_state_change",
                "invalid": "angry_alert",
            },
            "debounce_ms": 20,
            "slice_debounce_ms": 20,
            "reentry_debounce_ms": 50,
        },
        "desktop_environment": "auto",
        "de_defaults_applied": False,
        "language": "system",
        "theme": "catppuccin-mocha",
        "blur_enabled": True,
        "pointer": {"speed": 10, "acceleration": True},
        "scroll": {
            "natural": False,
            "smooth": True,
            "smartshift": True,
            "smartshift_threshold": 50,
            "mode": "smartshift",
        },
        "app": {"start_at_login": True, "show_tray_icon": True},
        "device_mode": "auto",
        "radial": {
            "minimal_mode": False,
        },
        "radial_menu": {
            "slices": [
                {
                    "label": "Play/Pause",
                    "action_id": "play_pause",
                    "type": "exec",
                    "command": "playerctl play-pause",
                    "color": "green",
                    "icon": "media-playback-start-symbolic",
                },
                {
                    "label": "New Note",
                    "action_id": "new_note",
                    "type": "exec",
                    "command": "kwrite",
                    "color": "yellow",
                    "icon": "document-new-symbolic",
                },
                {
                    "label": "Lock",
                    "action_id": "lock",
                    "type": "exec",
                    "command": "loginctl lock-session",
                    "color": "red",
                    "icon": "system-lock-screen-symbolic",
                },
                {
                    "label": "Settings",
                    "action_id": "settings",
                    "type": "settings",
                    "command": "",
                    "color": "mauve",
                    "icon": "emblem-system-symbolic",
                },
                {
                    "label": "Screenshot",
                    "action_id": "screenshot",
                    "type": "exec",
                    "command": "spectacle",
                    "color": "blue",
                    "icon": "camera-photo-symbolic",
                },
                {
                    "label": "Emoji",
                    "action_id": "emoji",
                    "type": "emoji",
                    "command": "",
                    "color": "pink",
                    "icon": "face-smile-symbolic",
                },
                {
                    "label": "Files",
                    "action_id": "files",
                    "type": "exec",
                    "command": "dolphin",
                    "color": "sapphire",
                    "icon": "folder-symbolic",
                },
                {
                    "label": "AI",
                    "action_id": "ai",
                    "type": "submenu",
                    "command": "",
                    "color": "teal",
                    "icon": "applications-science-symbolic",
                },
            ],
            "easy_switch_shortcuts": False,
            "easy_switch_host_os": ["linux", "unknown", "unknown"],
        },
    }

    def __init__(self):
        self.config = self._load()
        self._toast_callback = None

    def set_toast_callback(self, callback):
        """Set callback for showing toast notifications"""
        self._toast_callback = callback

    def _show_toast(self, message):
        """Show toast if callback is set"""
        if self._toast_callback:
            self._toast_callback(message)

    def _load(self) -> dict:
        """Load config from file or return defaults.

        On first run (de_defaults_applied is False), auto-detects the
        desktop environment and applies DE-appropriate commands to
        radial menu slices.
        """
        try:
            if self.CONFIG_FILE.exists():
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Merge with defaults to ensure all keys exist
                config = self._merge_defaults(loaded)
            else:
                config = json.loads(json.dumps(self.DEFAULT_CONFIG))
        except Exception as e:
            print(f"Error loading config: {e}")
            config = json.loads(json.dumps(self.DEFAULT_CONFIG))

        # Auto-apply DE defaults on first run
        if not config.get("de_defaults_applied", False):
            from settings_constants import (
                detect_desktop_environment,
                apply_de_defaults_to_slices,
            )

            de_key = detect_desktop_environment()
            slices = config.get("radial_menu", {}).get("slices", [])
            if slices:
                apply_de_defaults_to_slices(slices, de_key)
                config["radial_menu"]["slices"] = slices
            config["de_defaults_applied"] = True
            print(f"Auto-applied DE defaults for: {de_key}")

            # Save immediately so the flag persists
            try:
                self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                temp_path = self.CONFIG_FILE.with_suffix(".json.tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)
                os.replace(temp_path, self.CONFIG_FILE)
            except Exception as e:
                print(f"Error saving auto-detected DE defaults: {e}")

        return config

    def reload(self):
        """Reload config from disk - useful when settings window reopens"""
        self.config = self._load()
        return self.config

    def _merge_defaults(self, loaded: dict) -> dict:
        """Deep merge loaded config with defaults"""
        result = json.loads(json.dumps(self.DEFAULT_CONFIG))  # Deep copy
        self._deep_update(result, loaded)
        return result

    def _deep_update(self, base: dict, updates: dict):
        """Recursively update base dict with updates"""
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def save(self, show_toast=True):
        """Save config to file atomically and notify daemon"""
        try:
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            # Atomic write: write to temp file, then rename (atomic on POSIX)
            temp_path = self.CONFIG_FILE.with_suffix(".json.tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            # Atomic rename - replaces old file safely
            os.replace(temp_path, self.CONFIG_FILE)
            # Notify daemon to reload config
            self._notify_daemon()
            if show_toast:
                self._show_toast(_("Settings saved"))
        except Exception as e:
            print(f"Error saving config: {e}")
            self._show_toast(_("Error saving settings: {}").format(e))

    def _notify_daemon(self):
        """Notify daemon to reload config via D-Bus"""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.kde.juhradialmx",
                "/org/kde/juhradialmx/Daemon",
                "org.kde.juhradialmx.Daemon",
                None,
            )
            proxy.call_sync("ReloadConfig", None, Gio.DBusCallFlags.NONE, 500, None)
        except GLib.Error:
            pass  # Daemon may not be running

    def apply_to_device(self):
        """Apply settings to device via D-Bus and system utilities"""
        import subprocess
        import shlex

        script_path = Path(__file__).parent.parent / "scripts" / "apply-settings.sh"
        if script_path.exists() and not script_path.is_symlink():
            # Use shlex.quote to prevent command injection
            safe_path = shlex.quote(str(script_path))
            terminal = detect_terminal()
            # Build terminal command with -e flag (common across terminal emulators)
            subprocess.Popen(
                [
                    terminal,
                    "-e",
                    "bash",
                    "-c",
                    f'{safe_path}; echo ""; echo "Press Enter to close..."; read',
                ]
            )

    def get(self, *keys, default=None):
        """Get nested config value"""
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, *keys_and_value, auto_save=False):
        """Set nested config value and optionally save

        Args:
            *keys_and_value: Keys path followed by value
            auto_save: If False (default), just update in-memory. Use Apply button to save.
        """
        if len(keys_and_value) < 2:
            return
        *keys, value = keys_and_value
        target = self.config
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value
        if auto_save:
            self.save()


# Global config instance
config = ConfigManager()


# =============================================================================
# RADIAL MINIMAL MODE
# =============================================================================
def get_minimal_mode() -> bool:
    """Return True when minimal mode is enabled (icons only, no slices)."""
    return config.get("radial", "minimal_mode", default=False)


def set_minimal_mode(enabled: bool):
    """Enable or disable minimal mode and save config."""
    config.set("radial", "minimal_mode", enabled)
    config.save(show_toast=False)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def disable_scroll_on_scale(scale):
    """Disable scroll wheel on Gtk.Scale to prevent accidental value changes

    This prevents scroll events from changing slider values when scrolling
    in a ScrolledWindow. The slider will only respond to:
    - Direct click and drag
    - Arrow keys when focused
    """
    # Add scroll controller that consumes scroll events (returns True)
    scroll_controller = Gtk.EventControllerScroll.new(
        Gtk.EventControllerScrollFlags.VERTICAL
        | Gtk.EventControllerScrollFlags.HORIZONTAL
    )
    # Set to CAPTURE phase to intercept before the Scale widget sees it
    scroll_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    # Handler that consumes the scroll event (prevents it from reaching Scale)
    scroll_controller.connect("scroll", lambda controller, dx, dy: True)
    scale.add_controller(scroll_controller)


def detect_terminal():
    """Detect available terminal emulator with a fallback chain.

    Returns the first terminal found from the preferred list.
    """
    import shutil

    terminals = [
        "cosmic-term",
        "konsole",
        "gnome-terminal",
        "kgx",
        "kitty",
        "alacritty",
        "xterm",
    ]
    for term in terminals:
        if shutil.which(term):
            return term
    return "xterm"  # Last resort fallback


def detect_logitech_mouse():
    """Detect connected Logitech mouse name"""
    import subprocess
    import shutil
    from pathlib import Path

    # Logitech vendor ID
    LOGITECH_VENDOR = "046d"

    # Known MX Master device IDs and names (direct USB connection)
    DEVICE_NAMES = {
        "b034": "MX Master 4",
        "b035": "MX Master 4",
        "b023": "MX Master 3S",
        "b028": "MX Master 3S",
        "b024": "MX Master 3",
        "4082": "MX Master 3",
        "4069": "MX Master 2S",
        "4041": "MX Master",
    }

    try:
        # Method 1: Check HID devices for direct USB connection
        hid_path = Path("/sys/bus/hid/devices/")
        if hid_path.exists():
            for device in hid_path.iterdir():
                name = device.name.upper()
                if LOGITECH_VENDOR.upper() in name:
                    parts = name.split(":")
                    if len(parts) >= 3:
                        product_id = parts[2].split(".")[0].lower()
                        if product_id in DEVICE_NAMES:
                            return DEVICE_NAMES[product_id]

        # Method 2: Try libinput
        result = subprocess.run(
            ["libinput", "list-devices"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "MX Master" in line and "Device:" in line:
                    return line.split("Device:")[1].strip()

    except Exception as e:
        print(f"Device detection error: {e}")

    return "MX Master 4"  # Default fallback


# Cache the detected device name
_detected_device = None


def get_device_name():
    """Get detected device name (cached)"""
    global _detected_device
    if _detected_device is None:
        _detected_device = detect_logitech_mouse()
    return _detected_device


# =============================================================================
# GENERIC MOUSE MODE DETECTION (via D-Bus daemon)
# =============================================================================
_cached_device_mode = None


def _get_daemon_proxy():
    """Get a D-Bus proxy to the daemon. Returns None on failure."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.kde.juhradialmx",
            "/org/kde/juhradialmx/Daemon",
            "org.kde.juhradialmx.Daemon",
            None,
        )
    except GLib.Error:
        return None


def get_device_mode():
    """Get device mode: 'logitech' or 'generic'.

    Returns 'generic' only when the user has explicitly toggled it in settings.
    'auto' (default) and 'logitech' both resolve to 'logitech'.
    The daemon always runs both MX and generic evdev loops, so both mice
    work regardless - this setting only controls the UI layout.
    Result is cached for the lifetime of the process.
    """
    global _cached_device_mode
    if _cached_device_mode is not None:
        return _cached_device_mode

    configured = config.get("device_mode", default="auto")
    if configured == "generic":
        _cached_device_mode = "generic"
    else:
        _cached_device_mode = "logitech"
    return _cached_device_mode


def clear_device_mode_cache():
    """Clear the cached device mode so the next get_device_mode() re-reads config."""
    global _cached_device_mode
    _cached_device_mode = None


def get_device_name_from_daemon():
    """Get device name from daemon via D-Bus GetDeviceName().

    In forced generic mode (config override), scans for non-Logitech mice.
    Falls back to D-Bus daemon name, then existing detection.
    """
    # If user forced generic mode, find a non-Logitech mouse
    configured = config.get("device_mode", default="auto")
    if configured == "generic":
        name = _detect_non_logitech_mouse()
        if name:
            return name

    proxy = _get_daemon_proxy()
    if proxy:
        try:
            result = proxy.call_sync(
                "GetDeviceName", None,
                Gio.DBusCallFlags.NONE, 500, None,
            )
            if result:
                name = result.get_child_value(0).get_string()
                if name:
                    return name
        except GLib.Error:
            pass  # Method not yet implemented or daemon not running

    return get_device_name()


def _detect_non_logitech_mouse():
    """Scan /sys/class/input/ for non-Logitech mice. Returns name or None."""
    import subprocess
    try:
        result = subprocess.run(
            ["libinput", "list-devices"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0:
            return None
        current_name = None
        is_pointer = False
        for line in result.stdout.splitlines():
            if line.startswith("Device:"):
                current_name = line.split(":", 1)[1].strip()
                is_pointer = False
            elif "Capabilities:" in line and "pointer" in line:
                is_pointer = True
            elif line.strip() == "" and current_name and is_pointer:
                # Found a pointer device - skip Logitech ones
                lower = current_name.lower()
                if "logitech" not in lower and "logi" not in lower:
                    return current_name
                current_name = None
                is_pointer = False
        # Check last device
        if current_name and is_pointer:
            lower = current_name.lower()
            if "logitech" not in lower and "logi" not in lower:
                return current_name
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None
