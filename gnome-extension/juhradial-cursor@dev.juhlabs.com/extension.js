/**
 * JuhRadial Cursor Helper - GNOME Shell Extension
 *
 * Exposes the cursor position via D-Bus so JuhRadial MX can query it
 * on GNOME Wayland (where xdotool and Shell.Eval are unavailable).
 *
 * D-Bus interface:
 *   Name:   org.juhradial.CursorHelper
 *   Path:   /org/juhradial/CursorHelper
 *   Method: GetCursorPosition() -> (i, i)
 *
 * SPDX-License-Identifier: GPL-3.0
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const DBUS_IFACE = `
<node>
  <interface name="org.juhradial.CursorHelper">
    <method name="GetCursorPosition">
      <arg type="i" direction="out" name="x"/>
      <arg type="i" direction="out" name="y"/>
    </method>
  </interface>
</node>`;

export default class JuhRadialCursorExtension {
    _dbusId = null;
    _registrationId = null;

    enable() {
        const nodeInfo = Gio.DBusNodeInfo.new_for_xml(DBUS_IFACE);

        this._dbusId = Gio.bus_own_name(
            Gio.BusType.SESSION,
            'org.juhradial.CursorHelper',
            Gio.BusNameOwnerFlags.NONE,
            (connection) => {
                this._registrationId = connection.register_object(
                    '/org/juhradial/CursorHelper',
                    nodeInfo.interfaces[0],
                    (connection, _sender, _path, _iface, method, _params, invocation) => {
                        if (method === 'GetCursorPosition') {
                            const [x, y] = global.get_pointer();
                            invocation.return_value(
                                new GLib.Variant('(ii)', [x, y])
                            );
                        }
                    },
                    null,
                    null,
                );
            },
            null,
            null,
        );
    }

    disable() {
        if (this._dbusId) {
            Gio.bus_unown_name(this._dbusId);
            this._dbusId = null;
        }
        this._registrationId = null;
    }
}
