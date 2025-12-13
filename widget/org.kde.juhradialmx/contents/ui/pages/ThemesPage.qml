/*
 * Themes configuration page
 * SPDX-License-Identifier: GPL-3.0
 */

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: themesPage
    spacing: Kirigami.Units.largeSpacing

    Label {
        text: "Available Themes"
        font.bold: true
    }

    // Theme grid
    GridView {
        id: themeGrid
        Layout.fillWidth: true
        Layout.preferredHeight: 300
        cellWidth: 200
        cellHeight: 180
        clip: true

        model: ListModel {
            ListElement {
                name: "Catppuccin Mocha"
                background: "#1e1e2e"
                primary: "#cba6f7"
                isDefault: true
            }
            ListElement {
                name: "Vaporwave"
                background: "#1a1a2e"
                primary: "#ff71ce"
                isDefault: false
            }
            ListElement {
                name: "Matrix Rain"
                background: "#0d0d0d"
                primary: "#00ff41"
                isDefault: false
            }
        }

        delegate: ItemDelegate {
            width: themeGrid.cellWidth - 10
            height: themeGrid.cellHeight - 10

            Rectangle {
                anchors.fill: parent
                anchors.margins: 5
                radius: 8
                color: model.background
                border.color: themeGrid.currentIndex === index ? model.primary : "transparent"
                border.width: 2

                Column {
                    anchors.centerIn: parent
                    spacing: 10

                    Rectangle {
                        width: 60
                        height: 60
                        radius: 30
                        color: model.primary
                        opacity: 0.3
                        anchors.horizontalCenter: parent.horizontalCenter
                    }

                    Label {
                        text: model.name
                        color: "white"
                        anchors.horizontalCenter: parent.horizontalCenter
                    }

                    Label {
                        text: model.isDefault ? "(Default)" : ""
                        color: model.primary
                        font.pixelSize: 10
                        anchors.horizontalCenter: parent.horizontalCenter
                    }
                }
            }

            onClicked: themeGrid.currentIndex = index
        }
    }

    RowLayout {
        Button {
            text: "Apply Theme"
            icon.name: "dialog-ok-apply"
        }
        Button {
            text: "Preview Live"
            icon.name: "view-preview"
        }
        Item { Layout.fillWidth: true }
        Button {
            text: "Import Theme"
            icon.name: "document-import"
        }
    }
}
