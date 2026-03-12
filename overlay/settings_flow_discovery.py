#!/usr/bin/env python3
"""
JuhRadial MX - Flow Discovery & Pairing

FlowServiceListener (mDNS) and FlowDiscoveryMixin extracted from
settings_page_flow.py so the page file stays focused on UI layout
and toggle handlers.

SPDX-License-Identifier: GPL-3.0
"""

import logging
import socket
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, GLib, Adw

from i18n import _

# Try to import zeroconf for mDNS discovery
try:
    from zeroconf import ServiceBrowser, Zeroconf, ServiceInfo

    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False

# Flow module for multi-computer control
try:
    from flow import (
        get_flow_server,
        get_linked_computers,
        FlowClient,
        FLOW_PORT,
    )

    FLOW_MODULE_AVAILABLE = True
except ImportError:
    FLOW_MODULE_AVAILABLE = False

logger = logging.getLogger(__name__)


class FlowServiceListener:
    """mDNS service listener for discovering computers on the network"""

    def __init__(self, flow_page):
        self.flow_page = flow_page
        self.seen_ips = set()  # Track IPs to avoid duplicates

    def remove_service(self, zeroconf, type_, name):
        logger.debug("Service removed: %s", name)

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


class FlowDiscoveryMixin:
    """Mixin providing network discovery and pairing methods for FlowPage.

    Expects the consuming class to initialise these attributes in __init__:
      - self.discovered_computers  (dict)
      - self._zeroconf             (None)
      - self._registered_services  (list)
      - self.computers_box         (Gtk.Box)
      - self.no_computers_label    (Gtk.Label)
      - self.scan_button           (Gtk.Button)
    """

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
        # Merge mDNS-discovered + JuhFlow bridge peers
        all_computers = list(self.discovered_computers.values())
        all_computers.extend(self._get_bridge_peers())
        GLib.idle_add(self._update_computers_list, all_computers)
        return False

    def _get_bridge_peers(self):
        """Get connected JuhFlow bridge peers (Mac/Win companion apps)."""
        if not FLOW_MODULE_AVAILABLE:
            return []
        try:
            from flow import get_juhflow_bridge
            bridge = get_juhflow_bridge()
            if not bridge:
                return []
            peers = []
            for p in bridge.get_peers():
                # Avoid duplicates with mDNS results
                ip = p.get("ip", "")
                if ip in {c.get("ip") for c in self.discovered_computers.values()}:
                    continue
                peers.append({
                    "name": p.get("hostname", "Unknown"),
                    "ip": ip,
                    "port": 59872,
                    "software": "JuhFlow",
                    "service_type": "juhflow_bridge",
                })
            return peers
        except Exception:
            return []  # Bridge may not be initialized

    def _get_bridge_peer_ips(self):
        """Get set of IPs of connected JuhFlow bridge peers."""
        if not FLOW_MODULE_AVAILABLE:
            return set()
        try:
            from flow import get_juhflow_bridge
            bridge = get_juhflow_bridge()
            if bridge:
                return {p.get("ip", "") for p in bridge.get_peers()}
        except Exception:
            pass  # Bridge may not be initialized
        return set()

    def _discover_computers(self):
        """Discover other computers on the network running JuhRadialMX, Input Leap, or Logi Options+"""
        if not ZEROCONF_AVAILABLE:
            logger.warning("zeroconf not available, cannot discover computers")
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
                        logger.debug("Browsing for %s", svc_type)
                    except Exception as e:
                        logger.warning("Failed to browse %s: %s", svc_type, e)

                # Also register this computer as a JuhRadialMX service
                self._register_service(zc)

                # Keep browsing for a few seconds
                time.sleep(4)

                # Update UI on main thread (include bridge peers)
                all_computers = list(self.discovered_computers.values())
                all_computers.extend(self._get_bridge_peers())
                GLib.idle_add(
                    self._update_computers_list,
                    all_computers,
                )

            except Exception as e:
                logger.error("Discovery error: %s", e)
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
                        logger.debug("Zeroconf closed after discovery")
                    except Exception as e:
                        logger.error("Error closing Zeroconf: %s", e)
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
                logger.debug("Zeroconf cleaned up")
            except Exception as e:
                logger.error("Error cleaning up Zeroconf: %s", e)
            self._zeroconf = None

    def cleanup(self):
        """Called when the page is being destroyed or navigated away from"""
        if hasattr(self, "_juhflow_poll") and self._juhflow_poll:
            GLib.source_remove(self._juhflow_poll)
            self._juhflow_poll = None
        if hasattr(self, "_connect_reset_timer") and self._connect_reset_timer:
            GLib.source_remove(self._connect_reset_timer)
            self._connect_reset_timer = None
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
            logger.info(
                "Registered JuhRadialMX service: %s at %s:%s", hostname, local_ip, FLOW_PORT
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
                    logger.debug("Registered %s: %s", svc_type, hostname)
                except Exception as e:
                    logger.warning("Could not register %s: %s", svc_type, e)

        except Exception as e:
            logger.error("Failed to register service: %s", e)

    def add_discovered_computer(
        self, name, ip, port, software="Unknown", service_type=""
    ):
        """Called by ServiceListener when a computer is found (may be called from background thread)."""
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

        entry = {
            "name": clean_name,
            "ip": ip,
            "port": port,
            "software": software,
            "service_type": service_type,
        }
        # Use GLib.idle_add to safely mutate from any thread
        GLib.idle_add(self._store_discovered, name, entry)
        logger.info("Discovered: %s at %s:%s (Software: %s)", clean_name, ip, port, software)

    def _store_discovered(self, name, entry):
        """Store a discovered computer entry (runs on GTK main thread)."""
        self.discovered_computers[name] = entry
        return False  # Don't repeat

    def _update_computers_list(self, computers):
        """Update the list of detected computers"""
        # Clear existing items except the placeholder
        while child := self.computers_box.get_first_child():
            self.computers_box.remove(child)

        if not computers:
            # Re-add the existing placeholder label
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

        # Check if this computer's IP matches a connected JuhFlow bridge peer
        computer_ip = computer.get("ip", "")
        bridge_peer_ips = self._get_bridge_peer_ips()
        has_juhflow = computer_ip in bridge_peer_ips or software == "JuhFlow"

        # Link button / status label
        if has_juhflow:
            info_label = Gtk.Label(label=_("JuhFlow Available"))
            info_label.set_tooltip_text(
                _("JuhFlow companion app detected on this device")
            )
            info_label.add_css_class("success")
            info_label.add_css_class("caption")
            computer_box.append(info_label)
        elif software == "JuhRadialMX":
            link_btn = Gtk.Button(label=_("Link"))
            link_btn.add_css_class("suggested-action")
            link_btn.connect("clicked", self._on_link_clicked, computer)
            computer_box.append(link_btn)
        elif software == "Input Leap":
            info_label = Gtk.Label(label=_("Input Leap detected"))
            info_label.set_tooltip_text(
                _("This computer is running Input Leap (open-source KVM)")
            )
            info_label.add_css_class("accent-color")
            info_label.add_css_class("caption")
            computer_box.append(info_label)
        elif software == "Linux":
            info_label = Gtk.Label(label=_("Install JuhRadial MX"))
            info_label.set_tooltip_text(
                _("Install JuhRadial MX on this computer to enable Flow")
            )
            info_label.add_css_class("dim-label")
            info_label.add_css_class("caption")
            computer_box.append(info_label)
        elif software not in ("Unknown",):
            # macOS, Windows, SSH Server, Logi Options+, etc.
            info_label = Gtk.Label(label=_("Install JuhFlow"))
            info_label.set_tooltip_text(
                _("Install the JuhFlow companion app to enable Flow")
            )
            info_label.add_css_class("dim-label")
            info_label.add_css_class("caption")
            computer_box.append(info_label)

        return computer_box

    def _on_link_clicked(self, button, computer):
        """Handle click on Link button to pair with another computer"""
        if not FLOW_MODULE_AVAILABLE:
            logger.warning("Flow module not available")
            return

        # Get the Flow server and generate a pairing code
        server = get_flow_server()
        if not server:
            logger.warning("Flow server not running - enable Flow first")
            return

        computer_name = computer.get("name", "Unknown")
        computer_ip = computer.get("ip", "")
        computer_port = computer.get("port", FLOW_PORT)

        logger.info(
            "Initiating link with %s at %s:%s", computer_name, computer_ip, computer_port
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
                    logger.warning("Invalid pairing code - must be 6 digits")

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
            # Save the linked computer (including public key for crypto)
            linked_computers = get_linked_computers()
            linked_computers.add_computer(
                computer_name, computer_ip, computer_port, client.token,
                public_key=client.peer_public_key or ""
            )

            # Notify discovery about new peer key for encrypted beacons
            if client.peer_aes_key:
                from flow import get_logi_discovery
                discovery = get_logi_discovery()
                if discovery:
                    discovery.add_peer_key(computer_name, client.peer_aes_key)

            logger.info(
                "Successfully linked with %s (crypto: %s)",
                computer_name, "yes" if client.peer_public_key else "no"
            )

            # Show success toast
            toast = Adw.Toast(title=_("Linked with {}").format(computer_name))
            toast.set_timeout(3)
            window = self.get_root()
            if hasattr(window, "toast_overlay"):
                window.toast_overlay.add_toast(toast)
        else:
            logger.error("Failed to link with %s", computer_name)
