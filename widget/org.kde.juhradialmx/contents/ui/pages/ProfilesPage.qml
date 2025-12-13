/*
 * Profiles configuration page (Story 6.1)
 * SPDX-License-Identifier: GPL-3.0
 */

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

RowLayout {
    id: profilesPage
    spacing: Kirigami.Units.largeSpacing

    // Profile list (left panel)
    ColumnLayout {
        Layout.preferredWidth: 250
        Layout.fillHeight: true

        Label {
            text: "Profiles"
            font.bold: true
        }

        ListView {
            id: profileList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            model: ListModel {
                ListElement { name: "Default"; icon: "user-identity" }
                ListElement { name: "VS Code"; icon: "text-x-generic" }
                ListElement { name: "Firefox"; icon: "firefox" }
            }

            delegate: ItemDelegate {
                width: profileList.width
                highlighted: ListView.isCurrentItem
                onClicked: profileList.currentIndex = index

                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        source: model.icon
                        Layout.preferredWidth: 22
                        Layout.preferredHeight: 22
                    }
                    Label {
                        text: model.name
                        Layout.fillWidth: true
                    }
                }
            }
        }

        RowLayout {
            Button {
                text: "New"
                icon.name: "list-add"
            }
            Button {
                text: "Delete"
                icon.name: "edit-delete"
                enabled: profileList.currentIndex > 0 // Can't delete default
            }
        }
    }

    // Vertical separator
    Rectangle {
        Layout.preferredWidth: 1
        Layout.fillHeight: true
        color: Kirigami.Theme.disabledTextColor
        opacity: 0.3
    }

    // Radial menu preview (right panel)
    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        ColumnLayout {
            anchors.centerIn: parent
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                source: "view-list-icons"
                Layout.preferredWidth: 64
                Layout.preferredHeight: 64
                Layout.alignment: Qt.AlignHCenter
                opacity: 0.5
            }

            Label {
                text: "Radial Menu Preview"
                font.bold: true
                Layout.alignment: Qt.AlignHCenter
            }

            Label {
                text: "Visual radial menu editor will be implemented in Story 6.2"
                color: Kirigami.Theme.disabledTextColor
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
}
