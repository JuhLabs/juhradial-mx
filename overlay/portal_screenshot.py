#!/usr/bin/env python3
"""
JuhRadial MX - Interactive screenshot via the freedesktop Screenshot portal.

Standalone helper spawned by the overlay's screenshot action. The portal
Screenshot call is asynchronous: it returns a Request handle and the result
(the screenshot uri) arrives later on that Request's Response signal. The
portal also cancels the pending Request the instant the caller's D-Bus
connection drops, so a one-shot `gdbus call` dismisses the interactive picker
the moment gdbus exits. This helper holds its bus connection open on a GLib
main loop until Response arrives, so the picker stays up for the user.

Prints the screenshot uri to stdout and exits 0 on success; exits 0 silently
if the user cancels; exits 1 on error or after a 300s timeout.

SPDX-License-Identifier: GPL-3.0
"""

import sys
import secrets

try:
    from gi.repository import Gio, GLib
except ImportError as exc:
    sys.stderr.write(
        "portal_screenshot: python gobject introspection (gi) is required "
        f"but is not available: {exc}\n"
    )
    sys.exit(1)


PORTAL_NAME = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"
REQUEST_IFACE = "org.freedesktop.portal.Request"
TIMEOUT_SECONDS = 300


def main():
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as exc:
        sys.stderr.write(
            f"portal_screenshot: cannot connect to session bus: {exc}\n"
        )
        return 1

    # handle_token must be a valid object path element ([A-Za-z0-9_]); a random
    # hex suffix keeps it unique and non-guessable, per the portal spec.
    token = "juhradial_" + secrets.token_hex(8)

    # Expected Request object path (portal spec, since xdg-desktop-portal 0.9):
    # /org/freedesktop/portal/desktop/request/<SENDER>/<TOKEN>, where SENDER is
    # our unique bus name with the leading ':' stripped and every '.' -> '_'.
    sender = bus.get_unique_name()[1:].replace(".", "_")
    request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

    loop = GLib.MainLoop()
    state = {"code": 1}

    def on_response(_conn, _sender, _path, _iface, _signal, params, *_user):
        response, results = params.unpack()
        if response == 0:
            uri = results.get("uri", "")
            if uri:
                print(uri)
        # response 1 = user cancelled, 2 = ended another way: nothing to
        # capture, but the helper itself succeeded, so exit 0 silently.
        state["code"] = 0
        loop.quit()

    # Subscribe to Response BEFORE calling Screenshot: the spec requires this so
    # the portal cannot reply before we are listening (the race this helper is
    # here to avoid).
    sub_id = bus.signal_subscribe(
        PORTAL_NAME, REQUEST_IFACE, "Response", request_path, None,
        Gio.DBusSignalFlags.NONE, on_response,
    )

    options = {
        "handle_token": GLib.Variant("s", token),
        "interactive": GLib.Variant("b", True),
    }
    try:
        reply = bus.call_sync(
            PORTAL_NAME, PORTAL_PATH, SCREENSHOT_IFACE, "Screenshot",
            GLib.Variant("(sa{sv})", ("", options)),
            GLib.VariantType.new("(o)"),
            Gio.DBusCallFlags.NONE, -1, None,
        )
    except GLib.Error as exc:
        sys.stderr.write(f"portal_screenshot: Screenshot call failed: {exc}\n")
        bus.signal_unsubscribe(sub_id)
        return 1

    # Older portals may return a different handle than we precomputed; if so,
    # move the subscription onto the returned path (spec-recommended fallback).
    handle = reply.unpack()[0]
    if handle != request_path:
        bus.signal_unsubscribe(sub_id)
        bus.signal_subscribe(
            PORTAL_NAME, REQUEST_IFACE, "Response", handle, None,
            Gio.DBusSignalFlags.NONE, on_response,
        )

    def on_timeout():
        sys.stderr.write(
            "portal_screenshot: timed out waiting for the portal response\n"
        )
        state["code"] = 1
        loop.quit()
        return GLib.SOURCE_REMOVE

    GLib.timeout_add_seconds(TIMEOUT_SECONDS, on_timeout)
    loop.run()
    return state["code"]


if __name__ == "__main__":
    sys.exit(main())
