/*
 * JuhRadial MX Plasma Widget (Story 6.1)
 *
 * Settings dashboard for configuring radial menu profiles, themes, and haptics.
 * Provides an interactive MX Master 4 mouse preview with gesture button highlight.
 *
 * SPDX-License-Identifier: GPL-3.0
 */

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    // Compact representation (system tray icon)
    compactRepresentation: CompactRepresentation {}

    // Full representation (settings dashboard)
    fullRepresentation: FullRepresentation {}

    // Prefer compact in panel, expand on click
    preferredRepresentation: compactRepresentation

    // Widget hints
    toolTipMainText: "JuhRadial MX"
    toolTipSubText: "Click to configure radial menu"
}
