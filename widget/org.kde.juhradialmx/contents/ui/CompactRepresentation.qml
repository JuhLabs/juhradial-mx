/*
 * Compact representation for system tray (Story 6.1)
 * SPDX-License-Identifier: GPL-3.0
 */

import QtQuick
import org.kde.kirigami as Kirigami

Item {
    id: compactRoot

    // System tray icon with status indication
    Kirigami.Icon {
        id: trayIcon
        anchors.fill: parent
        source: "input-mouse"

        // Grayscale effect when not connected
        opacity: 1.0

        // TODO: Add badge overlay for status
        // - Green dot: Connected
        // - Yellow dot: Daemon running, no mouse
        // - Red dot: Daemon not running
    }

    // Status indicator badge (bottom-right corner)
    Rectangle {
        id: statusBadge
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: parent.width * 0.35
        height: width
        radius: width / 2

        // Color based on connection status
        // Default to green (connected) - will be updated by DaemonConnection
        color: Kirigami.Theme.positiveTextColor

        // Subtle border
        border.width: 1
        border.color: Kirigami.Theme.backgroundColor
    }

    MouseArea {
        anchors.fill: parent
        onClicked: {
            // Toggle full representation
            root.expanded = !root.expanded
        }
    }
}
