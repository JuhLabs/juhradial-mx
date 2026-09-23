import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
import "../components"

// Themes gallery: every colour theme as a large wallpaper tile with its accent
// and a miniature of the UI in that accent, plus the radial wheel skins, so
// both looks live on one tab. Hover previews the wallpaper, click commits.
Item {
    id: page
    anchors.fill: parent

    property string wheelKey: Backend.get("radial.wheel", "none")

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: themeCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: themeCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        width: parent.width
                        title: "Colour theme"
                        subtitle: "An accent and a matched wallpaper. The radial menu follows the accent."
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/preferences-desktop-theme-symbolic"
                        Badge { text: Theme.name; accent: true; dot: true }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    GridLayout {
                        id: grid
                        width: parent.width
                        columns: Math.max(2, Math.floor(width / 272))
                        columnSpacing: Theme.gap
                        rowSpacing: Theme.gap
                        Repeater {
                            model: Theme.themeList()
                            Item {
                                id: tile
                                required property var modelData
                                required property int index
                                readonly property bool sel: Theme.index === index
                                Layout.fillWidth: true
                                Layout.preferredHeight: 164
                                activeFocusOnTab: true
                                Keys.onSpacePressed: Theme.setIndex(index)
                                Keys.onReturnPressed: Theme.setIndex(index)

                                RectangularShadow {
                                    anchors.fill: parent; radius: 14; blur: 18; offset.y: 6
                                    color: tile.sel ? modelData.accent : "#000000"
                                    opacity: tile.sel ? 0.45 : 0.35
                                    Behavior on opacity { NumberAnimation { duration: Theme.dMed } }
                                }
                                Rectangle {
                                    id: frame
                                    anchors.fill: parent; radius: 14
                                    color: Theme.surfaceSolid
                                    border.width: tile.sel ? 2 : 1
                                    border.color: tile.activeFocus ? Theme.accent
                                                  : (tile.sel ? modelData.accent : (hov.hovered ? Theme.borderStrong : Theme.border))
                                    Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
                                    layer.enabled: true
                                    layer.effect: MultiEffect { maskEnabled: true; maskSource: tileMask }
                                    Image {
                                        anchors.fill: parent
                                        source: modelData.wallpaper
                                        sourceSize.width: 336; sourceSize.height: 244
                                        asynchronous: true
                                        fillMode: Image.PreserveAspectCrop; smooth: true
                                    }
                                    // bottom scrim so the label reads on any wallpaper
                                    Rectangle {
                                        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                                        height: 74
                                        gradient: Gradient {
                                            GradientStop { position: 0.0; color: "#00000000" }
                                            GradientStop { position: 1.0; color: "#B3000000" }
                                        }
                                    }
                                    // miniature of the UI in this accent: rail + two cards + a lit pill
                                    Item {
                                        anchors.right: parent.right; anchors.top: parent.top
                                        anchors.margins: 12
                                        width: 92; height: 58
                                        Rectangle { x: 0; y: 0; width: 26; height: 58; radius: 5; color: "#B0101216"; border.width: 1; border.color: "#22FFFFFF"
                                            Rectangle { x: 5; y: 9; width: 16; height: 5; radius: 2; color: modelData.accent }
                                            Rectangle { x: 5; y: 18; width: 16; height: 3; radius: 1.5; color: "#44FFFFFF" }
                                            Rectangle { x: 5; y: 25; width: 16; height: 3; radius: 1.5; color: "#44FFFFFF" }
                                        }
                                        Rectangle { x: 31; y: 0; width: 61; height: 26; radius: 5; color: "#A8141820"; border.width: 1; border.color: "#22FFFFFF"
                                            Rectangle { x: 6; y: 8; width: 26; height: 3; radius: 1.5; color: "#66FFFFFF" }
                                            Rectangle { x: 41; y: 7; width: 14; height: 8; radius: 4; color: modelData.accent
                                                Rectangle { x: 7; y: 1; width: 6; height: 6; radius: 3; color: "white" } }
                                        }
                                        Rectangle { x: 31; y: 32; width: 61; height: 26; radius: 5; color: "#A8141820"; border.width: 1; border.color: "#22FFFFFF"
                                            Rectangle { x: 6; y: 12; width: 44; height: 3; radius: 1.5; color: "#33FFFFFF"
                                                Rectangle { width: 26; height: 3; radius: 1.5; color: modelData.accent } }
                                        }
                                    }
                                    Row {
                                        anchors.left: parent.left; anchors.bottom: parent.bottom
                                        anchors.margins: 12; spacing: 9
                                        Rectangle {
                                            width: 22; height: 22; radius: 11; color: modelData.accent
                                            anchors.verticalCenter: parent.verticalCenter
                                            border.color: "#33FFFFFF"; border.width: 1
                                        }
                                        Text {
                                            text: modelData.name; color: "#FFFFFF"
                                            anchors.verticalCenter: parent.verticalCenter
                                            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                                            font.weight: tile.sel ? Font.DemiBold : Font.Medium
                                        }
                                    }
                                    Rectangle {
                                        visible: tile.sel
                                        anchors.bottom: parent.bottom; anchors.right: parent.right; anchors.margins: 12
                                        width: 22; height: 22; radius: 11; color: modelData.accent
                                        Text { anchors.centerIn: parent; text: "✓"; color: "#0A0A0A"
                                               font.pixelSize: 13; font.weight: Font.Bold }
                                    }
                                }
                                Rectangle { id: tileMask; anchors.fill: parent; radius: 14; visible: false; layer.enabled: true }
                                HoverHandler { id: hov }
                                TapHandler { onTapped: Theme.setIndex(index) }
                            }
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: wheelCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: wheelCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gap
                    CardHeader {
                        width: parent.width
                        title: "Radial wheel skin"
                        subtitle: "Independent of the colour theme. Your eight actions never move."
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-grid-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    WheelPicker {
                        width: parent.width
                        current: page.wheelKey
                        onSelected: (key) => { page.wheelKey = key; Backend.set("radial.wheel", key) }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
