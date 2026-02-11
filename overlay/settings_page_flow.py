#!/usr/bin/env python3
"""
JuhRadial MX - Flow Page

FlowPage and FlowServiceListener for multi-computer control.

SPDX-License-Identifier: GPL-3.0
"""

import socket
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, GLib, Gio, Adw

from i18n import _
from settings_config import config
from settings_widgets import SettingsCard, SettingRow

# Try to import zeroconf for mDNS discovery
try:
    from zeroconf import ServiceBrowser, Zeroconf, ServiceInfo

    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False

# Flow module for multi-computer control
try:
    from flow import (
        start_flow_server,
        stop_flow_server,
        get_flow_server,
        get_linked_computers,
        FlowClient,
        FLOW_PORT,
    )

    FLOW_MODULE_AVAILABLE = True
except ImportError:
    FLOW_MODULE_AVAILABLE = False


class FlowServiceListener:
    """mDNS service listener for discovering computers on the network"""

    def __init__(self, flow_page):
        self.flow_page = flow_page
        self.seen_ips = set()  # Track IPs to avoid duplicates

    def remove_service(self, zeroconf, type_, name):
        print(f"[Flow] Service removed: {name}")

    def add_service(self, zeroconf, type_, name):
        info = zeroconf.get_service_info(type_, name)
        if info:
            addresses = info.parsed_addresses()
            ip = addresses[0] if addresses else None
            if not ip or ip in self.seen_ips:
                return  # Skip if no IP or already seen
            self.seen_ips.add(ip)

            # Determine device/software type from service type
            if "juhradialmx" in type_:
                software = "JuhRadialMX"
            elif "inputleap" in type_.lower():
                software = "Input Leap"
            elif "logi" in type_.lower():
                software = "Logi Options+"
            elif "companion-link" in type_ or "airplay" in type_ or "raop" in type_:
                software = "macOS"
            elif "smb" in type_:
                software = "Windows/Samba"
            elif "workstation" in type_:
                software = "Linux"
            elif "rdp" in type_:
                software = "Windows RDP"
            elif "sftp" in type_ or "ssh" in type_:
                software = "SSH Server"
            else:
                software = "Computer"

            # Clean up name - remove service suffix
            clean_name = name.split("._")[0] if "._" in name else name
            # Remove MAC address prefix if present (e.g., "8E46296F5480@MacBook M4")
            if "@" in clean_name:
                clean_name = clean_name.split("@")[1]

            self.flow_page.add_discovered_computer(
                clean_name, ip, info.port, software, type_
            )

    def update_service(self, zeroconf, type_, name):
        pass  # Handle service updates if needed


class FlowPage(Gtk.ScrolledWindow):
    """Flow multi-computer control settings page"""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.discovered_computers = {}  # Store discovered computers
        self._zeroconf = None  # Track Zeroconf instance for cleanup
        self._registered_services = []  # Track registered ServiceInfo for unregistration

        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        main_box.set_margin_start(32)
        main_box.set_margin_end(32)
        main_box.set_margin_top(32)
        main_box.set_margin_bottom(32)

        # Header with Flow icon and description
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header_box.set_halign(Gtk.Align.CENTER)
        header_box.set_margin_bottom(16)

        header_icon = Gtk.Image.new_from_icon_name("view-dual-symbolic")
        header_icon.set_pixel_size(48)
        header_icon.add_css_class("accent-color")
        header_box.append(header_icon)

        header_title = Gtk.Label(label=_("Logitech Flow"))
        header_title.add_css_class("title-1")
        header_box.append(header_title)

        header_subtitle = Gtk.Label(label=_("Seamlessly move between computers"))
        header_subtitle.add_css_class("dim-label")
        header_box.append(header_subtitle)

        main_box.append(header_box)

        # Enable Flow Card
        enable_card = SettingsCard(_("Flow Control"))

        enable_row = SettingRow(
            _("Enable Flow"), _("Control multiple computers with one mouse")
        )
        self.flow_switch = Gtk.Switch()
        self.flow_switch.set_active(config.get("flow", "enabled", default=False))
        self.flow_switch.connect("state-set", self._on_flow_toggled)
        enable_row.set_control(self.flow_switch)
        enable_card.append(enable_row)

        # Edge trigger option
        edge_row = SettingRow(
            _("Switch at screen edge"), _("Move cursor to edge to switch computers")
        )
        self.edge_switch = Gtk.Switch()
        self.edge_switch.set_active(config.get("flow", "edge_trigger", default=True))
        self.edge_switch.set_sensitive(config.get("flow", "enabled", default=False))
        self.edge_switch.connect("state-set", self._on_edge_toggled)
        edge_row.set_control(self.edge_switch)
        enable_card.append(edge_row)

        main_box.append(enable_card)

        # Detected Computers Card
        computers_card = SettingsCard(_("Computers on Network"))

        self.computers_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.computers_box.set_margin_top(8)
        self.computers_box.set_margin_bottom(8)

        # Placeholder for no computers detected
        self.no_computers_label = Gtk.Label(label=_("No other computers detected"))
        self.no_computers_label.add_css_class("dim-label")
        self.no_computers_label.set_margin_top(16)
        self.no_computers_label.set_margin_bottom(16)
        self.computers_box.append(self.no_computers_label)

        computers_card.append(self.computers_box)

        # Scan button
        scan_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        scan_box.set_halign(Gtk.Align.END)
        scan_box.set_margin_top(8)

        self.scan_button = Gtk.Button(label=_("Scan Network"))
        self.scan_button.add_css_class("suggested-action")
        self.scan_button.connect("clicked", self._on_scan_clicked)
        scan_box.append(self.scan_button)

        computers_card.append(scan_box)

        main_box.append(computers_card)

        # How Flow Works Card
        info_card = SettingsCard(_("How Flow Works"))
        info_label = Gtk.Label()
        info_label.set_markup(
            _(
                "Logitech Flow allows you to seamlessly control multiple computers\n"
                "with a single mouse by moving your cursor to the edge of the screen."
            )
            + "\n\n"
            "<b>" + _("Requirements:") + "</b>\n"
            "  \u2022 " + _("JuhRadialMX running on all computers") + "\n"
            "  \u2022 " + _("Computers connected to the same network") + "\n"
            "  \u2022 " + _("Flow enabled on all devices") + "\n\n"
            "<b>" + _("Compatible Software Detected:") + "</b>\n"
            "  \u2022 " + _("JuhRadialMX instances") + "\n"
            '  \u2022 <a href="https://github.com/input-leap/input-leap">Input Leap</a> ('
            + _("open-source KVM")
            + ")\n"
            "  \u2022 Logi Options+ Flow\n\n"
            "<b>" + _("Features:") + "</b>\n"
            "  \u2022 " + _("Move cursor between screens seamlessly") + "\n"
            "  \u2022 " + _("Copy and paste across computers") + "\n"
            "  \u2022 " + _("Transfer files by dragging")
        )
        info_label.set_wrap(True)
        info_label.set_max_width_chars(50)
        info_label.set_halign(Gtk.Align.START)
        info_label.set_margin_top(8)
        info_label.set_margin_bottom(8)
        info_card.append(info_label)

        main_box.append(info_card)

        self.set_child(main_box)

        # Try to discover computers on startup
        GLib.idle_add(self._discover_computers)

    def _on_flow_toggled(self, switch, state):
        """Handle Flow enable/disable toggle"""
        config.set("flow", "enabled", state)
        # Enable/disable edge trigger based on Flow state
        self.edge_switch.set_sensitive(state)

        if FLOW_MODULE_AVAILABLE:
            if state:
                # Start the Flow server
                def on_host_change(new_host):
                    """Called when another computer changes hosts"""
                    print(f"[Flow] Received host change request: {new_host}")
                    # Switch our devices via D-Bus
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
                        proxy.call_sync(
                            "SetHost",
                            GLib.Variant("(y)", (new_host,)),
                            Gio.DBusCallFlags.NONE,
                            5000,
                            None,
                        )
                    except Exception as e:
                        print(f"[Flow] Error switching host: {e}")

                start_flow_server(on_host_change=on_host_change)
                print("[Flow] Server started")
            else:
                # Stop the Flow server
                stop_flow_server()
                print("[Flow] Server stopped")

        return False

    def _on_edge_toggled(self, switch, state):
        """Handle edge trigger toggle"""
        config.set("flow", "edge_trigger", state)
        return False

    def _on_scan_clicked(self, button):
        """Scan network for other computers running JuhRadialMX"""
        self.scan_button.set_sensitive(False)
        self.scan_button.set_label(_("Scanning..."))
        # Clear previous results and re-discover
        self.discovered_computers.clear()
        self._discover_computers()
        GLib.timeout_add(5000, self._finish_scan)

    def _finish_scan(self):
        """Complete the network scan"""
        self.scan_button.set_sensitive(True)
        self.scan_button.set_label(_("Scan Network"))
        # Update UI with discovered computers
        GLib.idle_add(
            self._update_computers_list, list(self.discovered_computers.values())
        )
        return False

    def _discover_computers(self):
        """Discover other computers on the network running JuhRadialMX, Input Leap, or Logi Options+"""
        if not ZEROCONF_AVAILABLE:
            print("[Flow] zeroconf not available, cannot discover computers")
            self._update_computers_list([])
            return False

        # Clean up any previous discovery session
        self._cleanup_zeroconf()

        # Service types to scan for
        SERVICE_TYPES = [
            "_juhradialmx._tcp.local.",
            # Input Leap / Barrier (open-source KVM software)
            "_inputLeapServerZeroconf._tcp.local.",
            "_inputLeapClientZeroconf._tcp.local.",
            # Logi Options+ Flow
            "_logiflow._tcp.local.",
            "_logitechflow._tcp.local.",
            "_logi-options._tcp.local.",
            # Common computer/device services
            "_companion-link._tcp.local.",  # Apple devices
            "_airplay._tcp.local.",  # AirPlay (Mac, Apple TV)
            "_smb._tcp.local.",  # Windows/Samba file sharing
            "_workstation._tcp.local.",  # Linux workstations
            "_sftp-ssh._tcp.local.",  # SSH/SFTP servers
            "_rdp._tcp.local.",  # Windows Remote Desktop
        ]

        # Start background discovery thread
        def discover_thread():
            zc = None
            try:
                zc = Zeroconf()
                self._zeroconf = zc
                listener = FlowServiceListener(self)
                browsers = []

                # Browse for all service types
                for svc_type in SERVICE_TYPES:
                    try:
                        browser = ServiceBrowser(zc, svc_type, listener)
                        browsers.append(browser)
                        print(f"[Flow] Browsing for {svc_type}")
                    except Exception as e:
                        print(f"[Flow] Failed to browse {svc_type}: {e}")

                # Also register this computer as a JuhRadialMX service
                self._register_service(zc)

                # Keep browsing for a few seconds
                time.sleep(4)

                # Update UI on main thread
                GLib.idle_add(
                    self._update_computers_list,
                    list(self.discovered_computers.values()),
                )

            except Exception as e:
                print(f"[Flow] Discovery error: {e}")
                GLib.idle_add(self._update_computers_list, [])
            finally:
                # Clean up Zeroconf resources after discovery completes
                if zc:
                    try:
                        for svc_info in self._registered_services:
                            try:
                                zc.unregister_service(svc_info)
                            except OSError:
                                pass  # Service already unregistered
                        self._registered_services.clear()
                        zc.close()
                        print("[Flow] Zeroconf closed after discovery")
                    except Exception as e:
                        print(f"[Flow] Error closing Zeroconf: {e}")
                    if self._zeroconf is zc:
                        self._zeroconf = None

        thread = threading.Thread(target=discover_thread, daemon=True)
        thread.start()
        return False

    def _cleanup_zeroconf(self):
        """Clean up any active Zeroconf instance"""
        if self._zeroconf:
            try:
                for svc_info in self._registered_services:
                    try:
                        self._zeroconf.unregister_service(svc_info)
                    except OSError:
                        pass  # Service already unregistered
                self._registered_services.clear()
                self._zeroconf.close()
                print("[Flow] Zeroconf cleaned up")
            except Exception as e:
                print(f"[Flow] Error cleaning up Zeroconf: {e}")
            self._zeroconf = None

    def cleanup(self):
        """Called when the page is being destroyed or navigated away from"""
        self._cleanup_zeroconf()

    def _register_service(self, zc):
        """Register this computer as a Flow-compatible service"""
        try:
            hostname = socket.gethostname()
            # Get local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()

            # Official Logi Options+ Flow port is 59866 (TCP)
            FLOW_PORT = 59866

            # Register as JuhRadialMX service
            info_juh = ServiceInfo(
                "_juhradialmx._tcp.local.",
                f"{hostname}._juhradialmx._tcp.local.",
                addresses=[socket.inet_aton(local_ip)],
                port=FLOW_PORT,
                properties={
                    "version": "1.0",
                    "hostname": hostname,
                    "flow": "compatible",
                },
            )
            zc.register_service(info_juh)
            self._registered_services.append(info_juh)
            print(
                f"[Flow] Registered JuhRadialMX service: {hostname} at {local_ip}:{FLOW_PORT}"
            )

            # Also register as potential Logi Flow compatible service
            # Logi Options+ may look for these service types
            for svc_type in ["_logiflow._tcp.local.", "_logitechflow._tcp.local."]:
                try:
                    info_logi = ServiceInfo(
                        svc_type,
                        f"{hostname}.{svc_type}",
                        addresses=[socket.inet_aton(local_ip)],
                        port=FLOW_PORT,
                        properties={
                            "version": "1.0",
                            "hostname": hostname,
                            "platform": "linux",
                        },
                    )
                    zc.register_service(info_logi)
                    self._registered_services.append(info_logi)
                    print(f"[Flow] Registered {svc_type}: {hostname}")
                except Exception as e:
                    print(f"[Flow] Could not register {svc_type}: {e}")

        except Exception as e:
            print(f"[Flow] Failed to register service: {e}")

    def add_discovered_computer(
        self, name, ip, port, software="Unknown", service_type=""
    ):
        """Called by ServiceListener when a computer is found"""
        # Don't add ourselves
        try:
            my_hostname = socket.gethostname()
            if name.startswith(my_hostname):
                return
        except OSError:
            pass  # Hostname lookup failed

        # Clean up service name from the display name
        clean_name = name
        for suffix in [
            "._juhradialmx._tcp.local.",
            "._logiflow._tcp.local.",
            "._logitechflow._tcp.local.",
            "._logi-options._tcp.local.",
        ]:
            clean_name = clean_name.replace(suffix, "")

        self.discovered_computers[name] = {
            "name": clean_name,
            "ip": ip,
            "port": port,
            "software": software,
            "service_type": service_type,
        }
        print(f"[Flow] Discovered: {clean_name} at {ip}:{port} (Software: {software})")

    def _update_computers_list(self, computers):
        """Update the list of detected computers"""
        # Clear existing items except the placeholder
        while child := self.computers_box.get_first_child():
            self.computers_box.remove(child)

        if not computers:
            # Show placeholder
            self.no_computers_label = Gtk.Label(label=_("No other computers detected"))
            self.no_computers_label.add_css_class("dim-label")
            self.no_computers_label.set_margin_top(16)
            self.no_computers_label.set_margin_bottom(16)
            self.computers_box.append(self.no_computers_label)
        else:
            # Show detected computers
            for computer in computers:
                computer_widget = self._create_computer_widget(computer)
                self.computers_box.append(computer_widget)

    def _create_computer_widget(self, computer):
        """Create a widget for a detected computer"""
        computer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        computer_box.set_margin_start(8)
        computer_box.set_margin_end(8)

        # Status indicator
        indicator = Gtk.Box()
        indicator.set_size_request(12, 12)
        indicator.add_css_class("connection-dot")
        indicator.add_css_class("connected")
        computer_box.append(indicator)

        # Computer icon
        comp_icon = Gtk.Image.new_from_icon_name("computer-symbolic")
        comp_icon.set_pixel_size(24)
        comp_icon.add_css_class("accent-color")
        computer_box.append(comp_icon)

        # Name and status
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)

        name_label = Gtk.Label(label=computer.get("name", _("Unknown")))
        name_label.set_halign(Gtk.Align.START)
        name_label.add_css_class("heading")
        text_box.append(name_label)

        # IP and software info row
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        info_box.set_halign(Gtk.Align.START)

        ip_label = Gtk.Label(label=computer.get("ip", ""))
        ip_label.add_css_class("dim-label")
        ip_label.add_css_class("caption")
        info_box.append(ip_label)

        # Software badge
        software = computer.get("software", "Unknown")
        software_label = Gtk.Label(label=software)
        software_label.add_css_class("caption")
        if software == "JuhRadialMX":
            software_label.add_css_class("accent-color")
        elif software == "Logi Options+":
            software_label.add_css_class("warning")
        else:
            software_label.add_css_class("dim-label")
        info_box.append(software_label)

        text_box.append(info_box)

        computer_box.append(text_box)

        # Link button - show for compatible computers
        software = computer.get("software", "Unknown")
        if software == "JuhRadialMX":
            link_btn = Gtk.Button(label=_("Link"))
            link_btn.add_css_class("suggested-action")
            link_btn.connect("clicked", self._on_link_clicked, computer)
            computer_box.append(link_btn)
        elif software == "Input Leap":
            # Input Leap is a compatible KVM - show as detected
            info_label = Gtk.Label(label=_("Input Leap detected"))
            info_label.set_tooltip_text(
                _("This computer is running Input Leap (open-source KVM)")
            )
            info_label.add_css_class("accent-color")
            info_label.add_css_class("caption")
            computer_box.append(info_label)
        elif software in (
            "Logi Options+",
            "macOS",
            "Windows/Samba",
            "Windows RDP",
            "Linux",
            "SSH Server",
            "Computer",
        ):
            # These are computers that could potentially run JuhRadialMX
            info_label = Gtk.Label(label=_("Install JuhRadialMX"))
            info_label.set_tooltip_text(
                _("Install JuhRadialMX on this computer to enable Flow linking")
            )
            info_label.add_css_class("dim-label")
            info_label.add_css_class("caption")
            computer_box.append(info_label)
        else:
            # Unknown devices
            pass  # Just show the device without any action button

        return computer_box

    def _on_link_clicked(self, button, computer):
        """Handle click on Link button to pair with another computer"""
        if not FLOW_MODULE_AVAILABLE:
            print("[Flow] Flow module not available")
            return

        # Get the Flow server and generate a pairing code
        server = get_flow_server()
        if not server:
            print("[Flow] Flow server not running - enable Flow first")
            return

        computer_name = computer.get("name", "Unknown")
        computer_ip = computer.get("ip", "")
        computer_port = computer.get("port", FLOW_PORT)

        print(
            f"[Flow] Initiating link with {computer_name} at {computer_ip}:{computer_port}"
        )

        # Show a pairing dialog
        self._show_pairing_dialog(computer_name, computer_ip, computer_port)

    def _show_pairing_dialog(self, computer_name, computer_ip, computer_port):
        """Show a dialog to pair with another computer"""
        # Create the dialog
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            heading=_("Link with {}").format(computer_name),
            body=_(
                "Enter the pairing code shown on {name} to link the computers.\n\n"
                "If you don't see a pairing code, open Flow settings on the other computer."
            ).format(name=computer_name),
        )

        # Add entry for pairing code
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)

        code_entry = Gtk.Entry()
        code_entry.set_placeholder_text(_("Enter 6-digit pairing code"))
        code_entry.set_max_length(6)
        code_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        content_box.append(code_entry)

        dialog.set_extra_child(content_box)

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("link", _("Link"))
        dialog.set_response_appearance("link", Adw.ResponseAppearance.SUGGESTED)

        def on_response(dialog, response):
            if response == "link":
                pairing_code = code_entry.get_text().strip()
                if len(pairing_code) == 6:
                    self._complete_pairing(
                        computer_name, computer_ip, computer_port, pairing_code
                    )
                else:
                    print("[Flow] Invalid pairing code - must be 6 digits")

        dialog.connect("response", on_response)
        dialog.present()

    def _complete_pairing(
        self, computer_name, computer_ip, computer_port, pairing_code
    ):
        """Complete the pairing process with another computer"""
        if not FLOW_MODULE_AVAILABLE:
            return

        # Create a Flow client and try to pair
        client = FlowClient(computer_ip, computer_port)
        my_hostname = socket.gethostname()

        if client.pair(pairing_code, my_hostname):
            # Save the linked computer
            linked_computers = get_linked_computers()
            linked_computers.add_computer(
                computer_name, computer_ip, computer_port, client.token
            )
            print(f"[Flow] Successfully linked with {computer_name}")

            # Show success toast
            toast = Adw.Toast(title=_("Linked with {}").format(computer_name))
            toast.set_timeout(3)
            # Find the toast overlay and show the toast
            window = self.get_root()
            if hasattr(window, "toast_overlay"):
                window.toast_overlay.add_toast(toast)
        else:
            print(f"[Flow] Failed to link with {computer_name}")
