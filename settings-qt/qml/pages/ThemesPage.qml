import QtQuick
import QtQuick.Layouts
import "../components"

// Colour themes: each is an accent + matched wallpaper. Live preview swatches.
Item {
    anchors.fill: parent
    GlassCard {
        anchors.fill: parent
        Column {
            anchors.fill: parent
            anchors.margins: Theme.padCard
            spacing: Theme.gap
            CardHeader {
                width: parent.width
                title: "Color theme"
                subtitle: "Each theme pairs an accent with a matched wallpaper"
                icon: "image://icon/" + Theme.accent.toString().slice(1) + "/preferences-desktop-theme-symbolic"
            }
            Rectangle { width: parent.width; height: 1; color: Theme.border }
            Flickable {
                width: parent.width
                height: parent.height - parent.spacing * 2 - 56
                contentHeight: flow.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Flow {
                    id: flow
                    width: parent.width
                    spacing: Theme.gap
                    Repeater {
                        model: Theme.themeList()
                        Rectangle {
                            id: sw
                            required property var modelData
                            required property int index
                            width: 168; height: 122; radius: 14
                            color: Theme.surfaceSolid
                            border.width: (Theme.index === index || sw.activeFocus) ? 2 : 1
                            border.color: sw.activeFocus ? Theme.accent
                                          : (Theme.index === index ? modelData.accent : Theme.border)
                            clip: true
                            activeFocusOnTab: true
                            Keys.onSpacePressed: Theme.setIndex(index)
                            Keys.onReturnPressed: Theme.setIndex(index)
                            Behavior on border.color { ColorAnimation { duration: Theme.dShort } }
                            scale: hov.hovered ? 1.03 : 1.0
                            Behavior on scale { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }

                            Image {
                                anchors.fill: parent
                                source: modelData.wallpaper
                                sourceSize.width: 336; sourceSize.height: 244
                                // Decode the twelve tiles off the GUI thread: a synchronous
                                // decode made this tab the slowest switch (~150 ms).
                                asynchronous: true
                                fillMode: Image.PreserveAspectCrop; smooth: true
                            }
                            Rectangle { anchors.fill: parent; color: "#55000000" }
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
                                    font.weight: Theme.index === index ? Font.DemiBold : Font.Medium
                                }
                            }
                            Rectangle {
                                visible: Theme.index === index
                                anchors.top: parent.top; anchors.right: parent.right; anchors.margins: 8
                                width: 22; height: 22; radius: 11; color: modelData.accent
                                Text { anchors.centerIn: parent; text: "✓"; color: "#0A0A0A"
                                       font.pixelSize: 13; font.weight: Font.Bold }
                            }
                            HoverHandler { id: hov }
                            TapHandler { onTapped: Theme.setIndex(index) }
                        }
                    }
                }
            }
        }
    }
}
