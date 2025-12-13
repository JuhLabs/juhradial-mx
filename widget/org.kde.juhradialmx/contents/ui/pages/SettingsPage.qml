/*
 * Haptics & General Settings page
 * SPDX-License-Identifier: GPL-3.0
 */

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: settingsPage
    spacing: Kirigami.Units.largeSpacing

    // Haptic Feedback Section
    Kirigami.FormLayout {
        Layout.fillWidth: true

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Haptic Feedback"
        }

        Switch {
            id: hapticsEnabledSwitch
            Kirigami.FormData.label: "Enable haptics:"
            checked: true
        }

        RowLayout {
            Kirigami.FormData.label: "Intensity:"
            enabled: hapticsEnabledSwitch.checked

            Slider {
                id: intensitySlider
                from: 0
                to: 100
                value: 50
                stepSize: 5
                Layout.preferredWidth: 200
            }

            Label {
                text: intensitySlider.value + "%"
                Layout.preferredWidth: 40
            }

            Button {
                text: "Test"
                icon.name: "media-playback-start"
                onClicked: {
                    // TODO: Send test haptic via D-Bus
                }
            }
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Haptic Events"
        }

        RowLayout {
            Kirigami.FormData.label: "Menu appear:"
            enabled: hapticsEnabledSwitch.checked

            Slider {
                from: 0; to: 100; value: 20; stepSize: 5
                Layout.preferredWidth: 150
            }
            Label { text: "20%" }
        }

        RowLayout {
            Kirigami.FormData.label: "Slice change:"
            enabled: hapticsEnabledSwitch.checked

            Slider {
                from: 0; to: 100; value: 40; stepSize: 5
                Layout.preferredWidth: 150
            }
            Label { text: "40%" }
        }

        RowLayout {
            Kirigami.FormData.label: "Confirm selection:"
            enabled: hapticsEnabledSwitch.checked

            Slider {
                from: 0; to: 100; value: 80; stepSize: 5
                Layout.preferredWidth: 150
            }
            Label { text: "80%" }
        }
    }

    Item { Layout.fillHeight: true }

    // Export/Import Section
    RowLayout {
        Layout.fillWidth: true

        Button {
            text: "Export Configuration"
            icon.name: "document-export"
        }

        Button {
            text: "Import Configuration"
            icon.name: "document-import"
        }

        Item { Layout.fillWidth: true }

        Button {
            text: "Reset to Defaults"
            icon.name: "edit-undo"
        }
    }
}
