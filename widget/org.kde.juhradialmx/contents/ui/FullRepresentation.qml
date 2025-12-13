/*
 * Full representation - Settings Dashboard (Story 6.1)
 *
 * Main settings dashboard with:
 * - Interactive MX Master 4 mouse preview
 * - Daemon connection status
 * - Tab navigation for profiles, themes, haptics
 *
 * SPDX-License-Identifier: GPL-3.0
 */

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

import "components"
import "pages"

ColumnLayout {
    id: fullRoot

    Layout.minimumWidth: 800
    Layout.minimumHeight: 600
    Layout.preferredWidth: 900
    Layout.preferredHeight: 700

    // D-Bus connection to daemon
    DaemonConnection {
        id: daemon

        onDaemonStatusChanged: function(running) {
            if (!running) {
                statusLabel.text = "Daemon Not Running"
                statusLabel.color = Kirigami.Theme.negativeTextColor
            }
        }

        onMouseStatusChanged: function(connected) {
            if (connected && daemon.daemonRunning) {
                statusLabel.text = "Connected"
                statusLabel.color = Kirigami.Theme.positiveTextColor
            } else if (daemon.daemonRunning) {
                statusLabel.text = "Mouse Not Detected"
                statusLabel.color = Kirigami.Theme.neutralTextColor
            }
        }
    }

    // Header with title and status
    RowLayout {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.largeSpacing

        Kirigami.Heading {
            text: "JuhRadial MX"
            level: 1
        }

        Item { Layout.fillWidth: true }

        // Connection status indicator
        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Rectangle {
                width: 10
                height: 10
                radius: 5
                color: daemon.fullyConnected
                    ? Kirigami.Theme.positiveTextColor
                    : daemon.daemonRunning
                        ? Kirigami.Theme.neutralTextColor
                        : Kirigami.Theme.negativeTextColor

                SequentialAnimation on opacity {
                    running: daemon.fullyConnected
                    loops: Animation.Infinite
                    NumberAnimation { to: 1.0; duration: 1000 }
                    NumberAnimation { to: 0.5; duration: 1000 }
                }
            }

            Label {
                id: statusLabel
                text: daemon.fullyConnected
                    ? "Connected"
                    : daemon.daemonRunning
                        ? "Mouse Not Detected"
                        : "Daemon Not Running"
                color: daemon.fullyConnected
                    ? Kirigami.Theme.positiveTextColor
                    : daemon.daemonRunning
                        ? Kirigami.Theme.neutralTextColor
                        : Kirigami.Theme.negativeTextColor
            }
        }
    }

    // Tab bar for navigation
    TabBar {
        id: tabBar
        Layout.fillWidth: true

        TabButton {
            text: "Overview"
            icon.name: "input-mouse"
        }
        TabButton {
            text: "Profiles"
            icon.name: "user-identity"
        }
        TabButton {
            text: "Themes"
            icon.name: "preferences-desktop-theme"
        }
        TabButton {
            text: "Haptics"
            icon.name: "preferences-desktop-notification-bell"
        }
        TabButton {
            text: "Advanced"
            icon.name: "configure"
        }
    }

    // Tab content
    StackLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        currentIndex: tabBar.currentIndex

        // Overview page with mouse preview (Story 6.1)
        RowLayout {
            spacing: Kirigami.Units.largeSpacing

            // Left panel: Mouse preview
            MousePreview {
                id: mousePreview
                Layout.preferredWidth: 260
                Layout.fillHeight: true

                connected: daemon.fullyConnected
                mouseDetected: daemon.mouseConnected
                daemonRunning: daemon.daemonRunning
                statusMessage: daemon.lastError

                onGestureButtonClicked: {
                    // Trigger a test haptic when gesture button clicked in preview
                    if (daemon.fullyConnected) {
                        daemon.testHaptic(50)  // 50% intensity test
                    }
                }
            }

            // Separator
            Rectangle {
                Layout.preferredWidth: 1
                Layout.fillHeight: true
                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.bottomMargin: Kirigami.Units.largeSpacing
                color: Kirigami.Theme.disabledTextColor
                opacity: 0.3
            }

            // Right panel: Quick info and actions
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: Kirigami.Units.largeSpacing
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Heading {
                    text: "Welcome to JuhRadial MX"
                    level: 2
                }

                Label {
                    Layout.fillWidth: true
                    text: "JuhRadial MX provides a customizable radial menu for your " +
                          "Logitech MX Master 4 mouse. Hold the gesture button to open " +
                          "the menu, move to select, and release to execute."
                    wrapMode: Text.WordWrap
                    color: Kirigami.Theme.textColor
                }

                // Quick status cards
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    rowSpacing: Kirigami.Units.smallSpacing
                    columnSpacing: Kirigami.Units.smallSpacing

                    // Active Profile card
                    Kirigami.AbstractCard {
                        Layout.fillWidth: true
                        contentItem: ColumnLayout {
                            spacing: Kirigami.Units.smallSpacing

                            RowLayout {
                                Kirigami.Icon {
                                    source: "user-identity"
                                    Layout.preferredWidth: 24
                                    Layout.preferredHeight: 24
                                }
                                Label {
                                    text: "Active Profile"
                                    font.bold: true
                                }
                            }
                            Label {
                                text: "Default"
                                color: Kirigami.Theme.highlightColor
                            }
                        }
                    }

                    // Active Theme card
                    Kirigami.AbstractCard {
                        Layout.fillWidth: true
                        contentItem: ColumnLayout {
                            spacing: Kirigami.Units.smallSpacing

                            RowLayout {
                                Kirigami.Icon {
                                    source: "preferences-desktop-theme"
                                    Layout.preferredWidth: 24
                                    Layout.preferredHeight: 24
                                }
                                Label {
                                    text: "Theme"
                                    font.bold: true
                                }
                            }
                            Label {
                                text: "Catppuccin Mocha"
                                color: Kirigami.Theme.highlightColor
                            }
                        }
                    }

                    // Haptic Status card
                    Kirigami.AbstractCard {
                        Layout.fillWidth: true
                        contentItem: ColumnLayout {
                            spacing: Kirigami.Units.smallSpacing

                            RowLayout {
                                Kirigami.Icon {
                                    source: "preferences-desktop-notification-bell"
                                    Layout.preferredWidth: 24
                                    Layout.preferredHeight: 24
                                }
                                Label {
                                    text: "Haptics"
                                    font.bold: true
                                }
                            }
                            Label {
                                text: daemon.fullyConnected ? "Enabled (50%)" : "Unavailable"
                                color: daemon.fullyConnected
                                    ? Kirigami.Theme.positiveTextColor
                                    : Kirigami.Theme.disabledTextColor
                            }
                        }
                    }

                    // Connection card
                    Kirigami.AbstractCard {
                        Layout.fillWidth: true
                        contentItem: ColumnLayout {
                            spacing: Kirigami.Units.smallSpacing

                            RowLayout {
                                Kirigami.Icon {
                                    source: "network-connect"
                                    Layout.preferredWidth: 24
                                    Layout.preferredHeight: 24
                                }
                                Label {
                                    text: "Connection"
                                    font.bold: true
                                }
                            }
                            Label {
                                text: daemon.fullyConnected ? "USB" : "Not Connected"
                                color: daemon.fullyConnected
                                    ? Kirigami.Theme.positiveTextColor
                                    : Kirigami.Theme.negativeTextColor
                            }
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                // Quick actions
                RowLayout {
                    Layout.alignment: Qt.AlignRight
                    spacing: Kirigami.Units.smallSpacing

                    Button {
                        text: "Test Menu"
                        icon.name: "view-list-icons"
                        enabled: daemon.fullyConnected

                        onClicked: {
                            // Show menu at screen center for testing
                            daemon.showMenuAt(960, 540)
                        }
                    }

                    Button {
                        text: "Reload Config"
                        icon.name: "view-refresh"
                        enabled: daemon.daemonRunning

                        onClicked: {
                            daemon.reloadConfig()
                        }
                    }
                }
            }
        }

        // Profiles page
        Loader {
            source: "pages/ProfilesPage.qml"
            active: tabBar.currentIndex === 1
        }

        // Themes page
        Loader {
            source: "pages/ThemesPage.qml"
            active: tabBar.currentIndex === 2
        }

        // Haptics page (Settings)
        Loader {
            source: "pages/SettingsPage.qml"
            active: tabBar.currentIndex === 3
        }

        // Advanced page (P2 features)
        Item {
            ColumnLayout {
                anchors.centerIn: parent
                spacing: Kirigami.Units.largeSpacing

                Kirigami.Icon {
                    source: "configure"
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: 64
                    Layout.alignment: Qt.AlignHCenter
                    opacity: 0.5
                }

                Label {
                    text: "Advanced Features"
                    font.bold: true
                    Layout.alignment: Qt.AlignHCenter
                }

                Label {
                    text: "Plasma Activities integration and idle animations\nwill be available in a future update."
                    color: Kirigami.Theme.disabledTextColor
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }
}
