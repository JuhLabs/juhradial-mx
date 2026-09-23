import QtQuick
import QtQuick.Layouts
import "../components"

// Logitech Easy-Switch: pair up to 3 hosts and jump between them.
Item {
    id: page
    anchors.fill: parent

    readonly property string _ic: "image://icon/" + Theme.accent.toString().slice(1) + "/"

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

            // ---- Generic fallback ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: 120
                visible: Backend.isGeneric
                Column {
                    anchors.centerIn: parent
                    spacing: Theme.gapS
                    ActionIcon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        iconName: "network-wireless-disconnected-symbolic"; tint: Theme.textMuted; px: 26
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Easy-Switch requires a Logitech device"
                        color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                    }
                }
            }

            // ---- Easy-Switch ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: esCol.implicitHeight + Theme.padCard * 2
                visible: !Backend.isGeneric
                Column {
                    id: esCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS

                    // Hero header with illustration
                    Item {
                        id: esHeader
                        width: parent.width
                        height: 80
                        Image {
                            id: spotImg
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            source: assetsDir + "/spots/spot_devices.png"
                            sourceSize.width: 160; sourceSize.height: 160
                            width: 80; height: 80
                            fillMode: Image.PreserveAspectFit
                            smooth: true; opacity: 0.92
                        }
                        RowLayout {
                            anchors.left: parent.left
                            anchors.right: spotImg.left
                            anchors.rightMargin: Theme.gapL
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 12
                            ActionIcon {
                                Layout.alignment: Qt.AlignVCenter
                                iconName: "network-wireless-symbolic"; tint: Theme.accent; px: 26
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 3
                                Text {
                                    text: "Easy-Switch"; color: Theme.textPrimary
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsH2; font.weight: Font.DemiBold
                                    Layout.fillWidth: true; elide: Text.ElideRight
                                }
                                Text {
                                    text: "Pair up to 3 computers and jump between them"
                                    color: Theme.textMuted
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Easy-Switch shortcuts in radial menu"
                        desc: "Show host-switch slices in the gesture menu"
                        Toggle {
                            checked: Backend.get("radial_menu.easy_switch_shortcuts", true)
                            onToggled: (v) => Backend.setLocal("radial_menu.easy_switch_shortcuts", v)
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    Item {
                        width: parent.width; height: 24
                        SectionHeader {
                            text: "Paired computers"
                            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                        }
                        IconButton {
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            icon: "view-refresh-symbolic"; tint: Theme.textMuted; diameter: 30
                            onClicked: Backend.refreshDevices()
                        }
                    }

                    Repeater {
                        model: 3
                        Rectangle {
                            id: hostCard
                            required property int index
                            readonly property bool active: Backend.currentHost === index
                            width: esCol.width
                            implicitHeight: 64
                            radius: Theme.radiusCtl
                            color: active ? Theme.accentSubtle
                                          : (cardMa.containsMouse ? "#14FFFFFF" : "#0CFFFFFF")
                            border.width: active ? 2 : 1
                            border.color: active ? Theme.accent : Theme.border
                            Behavior on color { ColorAnimation { duration: Theme.dShort } }
                            Behavior on border.color { ColorAnimation { duration: Theme.dShort } }

                            // Clicking a non-active slot switches to it. Declared first so
                            // the ComboBox and Switch button on top intercept their own clicks.
                            MouseArea {
                                id: cardMa
                                anchors.fill: parent
                                enabled: !hostCard.active
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: Backend.switchHost(hostCard.index)
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14; anchors.rightMargin: 14
                                spacing: Theme.gapL

                                // Big host number
                                Rectangle {
                                    Layout.alignment: Qt.AlignVCenter
                                    width: 40; height: 40; radius: 11
                                    color: hostCard.active ? Theme.accent : "#14FFFFFF"
                                    border.width: 1
                                    border.color: hostCard.active ? Theme.accent : Theme.border
                                    Behavior on color { ColorAnimation { duration: Theme.dShort } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: hostCard.index + 1
                                        color: hostCard.active ? "#0A0A0A" : Theme.textBody
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsH3
                                        font.weight: Font.DemiBold
                                    }
                                }

                                // OS icon
                                ActionIcon {
                                    Layout.alignment: Qt.AlignVCenter
                                    iconName: "computer-symbolic"
                                    tint: hostCard.active ? Theme.accent : Theme.textMuted
                                    px: 22
                                }

                                // Host name + hint
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text {
                                        text: Backend.hostNames[hostCard.index]
                                              ? Backend.hostNames[hostCard.index]
                                              : "Host " + (hostCard.index + 1)
                                        color: Theme.textPrimary
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                                        font.weight: Font.DemiBold
                                        Layout.fillWidth: true; elide: Text.ElideRight
                                    }
                                    Text {
                                        text: hostCard.active ? "Connected now" : "Tap to switch"
                                        color: Theme.textMuted
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                    }
                                }

                                Badge {
                                    Layout.alignment: Qt.AlignVCenter
                                    visible: hostCard.active
                                    text: "Active"; accent: true; dot: true
                                }

                                ComboBox {
                                    Layout.preferredWidth: 150
                                    Layout.alignment: Qt.AlignVCenter
                                    model: Backend.easySwitchOs()
                                    currentId: (Backend.get("radial_menu.easy_switch_host_os", [])[hostCard.index] || "unknown")
                                    onActivated2: (id) => Backend.setHostOs(hostCard.index, id)
                                }

                                PrimaryButton {
                                    Layout.alignment: Qt.AlignVCenter
                                    visible: !hostCard.active
                                    text: "Switch"; ghost: true
                                    onClicked: Backend.switchHost(hostCard.index)
                                }
                            }
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }

    // Refresh the active-host highlight when the daemon reports a switch.
    Connections { target: Backend; function onLiveChanged() {} }
}
