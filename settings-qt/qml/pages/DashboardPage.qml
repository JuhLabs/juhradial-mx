import QtQuick
import QtQuick.Layouts
import "../components"

// Landing dashboard: device hero, live stats, status badges, system info.
Item {
    id: page
    anchors.fill: parent

    // Config-derived values have no NOTIFY, so refresh them on live updates.
    property string wheelMode: Backend.get("scroll.mode", "smartshift")
    property bool gamingOn: Backend.get("gaming.enabled", false)
    property bool flowOn: Backend.get("flow.enabled", false)

    function _cap(s) { return s.length ? s.charAt(0).toUpperCase() + s.slice(1) : s }

    property var actMap: ({})
    property string wheelKey: Backend.get("radial.wheel", "azure")
    property bool mono: Backend.get("radial.monochrome_icons", false)
    Component.onCompleted: {
        var a = Backend.buttonActions(), m = {}
        for (var i = 0; i < a.length; i++) m[a[i].id] = a[i].name
        actMap = m
    }
    function actionName(slot, def) {
        var id = Backend.get("buttons." + slot, def)
        return actMap[id] || id
    }

    Connections {
        target: Backend
        function onLiveChanged() {
            page.wheelMode = Backend.get("scroll.mode", "smartshift")
            page.gamingOn = Backend.get("gaming.enabled", false)
            page.flowOn = Backend.get("flow.enabled", false)
            page.wheelKey = Backend.get("radial.wheel", "azure")
        }
    }

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
            id: col
            width: parent.width
            spacing: Theme.gap

            // ---- Hero ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: 170
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.pad
                    spacing: Theme.pad

                    Image {
                        source: assetsDir + "/devices/mx4_side.png"
                        sourceSize.width: 1289; sourceSize.height: 829
                        Layout.preferredHeight: 124
                        Layout.preferredWidth: 193
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        Layout.alignment: Qt.AlignVCenter
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignVCenter
                        spacing: Theme.gapS

                        Text {
                            text: Backend.deviceName
                            color: Theme.textPrimary
                            font.family: Theme.fontUI
                            font.pixelSize: Theme.fsH2
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        Badge {
                            text: Backend.daemonAvailable ? "Connected" : "Daemon offline"
                            accent: Backend.daemonAvailable
                            dot: Backend.daemonAvailable
                        }
                        Text {
                            text: Backend.daemonAvailable
                                  ? "Gesture button, thumb wheel and haptics ready."
                                  : "Start the JuhRadial daemon to control this device."
                            color: Theme.textMuted
                            font.family: Theme.fontUI
                            font.pixelSize: Theme.fsSmall
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                    }

                    BatteryRing {
                        percent: Backend.battery
                        charging: Backend.charging
                        size: 120
                        Layout.alignment: Qt.AlignVCenter
                    }
                }
            }

            // ---- Live stat tiles (each links to its tab) ----
            GridLayout {
                Layout.fillWidth: true
                columns: 4
                columnSpacing: Theme.gap
                rowSpacing: Theme.gap

                component StatCard: GlassCard {
                    id: statCard
                    property string toTab: ""
                    Layout.fillWidth: true
                    Layout.preferredHeight: 96
                    scale: scMa.containsMouse ? 1.03 : 1.0
                    Behavior on scale { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }
                    MouseArea {
                        id: scMa; anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: if (statCard.toTab !== "") Backend.goTo(statCard.toTab)
                    }
                }

                StatCard {
                    toTab: "scroll"
                    StatTile { anchors.fill: parent; value: Backend.dpi; label: "DPI"; icon: "input-mouse-symbolic" }
                }
                StatCard {
                    toTab: "scroll"
                    StatTile { anchors.fill: parent; value: page._cap(Backend.wheelMode !== "" ? Backend.wheelMode : page.wheelMode); label: "Wheel mode"; icon: "view-list-symbolic" }
                }
                StatCard {
                    toTab: "themes"
                    // theme tile: wallpaper thumbnail + accent + name
                    Column {
                        anchors.centerIn: parent; spacing: 7
                        Rectangle {
                            width: 64; height: 38; radius: 9; clip: true
                            anchors.horizontalCenter: parent.horizontalCenter
                            color: Theme.surfaceSolid
                            border.color: Theme.border; border.width: 1
                            Image {
                                anchors.fill: parent
                                source: Theme.wallpaper
                                sourceSize.width: 256; sourceSize.height: 152
                                asynchronous: true
                                fillMode: Image.PreserveAspectCrop; smooth: true
                            }
                            Rectangle {
                                anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 4
                                width: 12; height: 12; radius: 6; color: Theme.accent
                                border.color: "#55FFFFFF"; border.width: 1
                            }
                        }
                        Text {
                            text: Theme.name; color: Theme.textPrimary
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
                            anchors.horizontalCenter: parent.horizontalCenter
                        }
                    }
                }
                StatCard {
                    toTab: "haptics"
                    StatTile { anchors.fill: parent; value: Backend.hapticsEnabled ? "On" : "Off"; label: "Haptics"; icon: "audio-volume-medium-symbolic" }
                }
            }

            // ---- At a glance ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: glanceCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: glanceCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "At a glance"; subtitle: "Current mode and paired hosts"
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/view-grid-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    Flow {
                        width: parent.width
                        spacing: Theme.gapS
                        topPadding: 2
                        Badge {
                            text: "Easy-Switch host " + (Backend.currentHost + 1)
                            dot: true
                        }
                        Badge { text: Backend.numHosts + " paired hosts" }
                        Badge {
                            text: "Gaming " + (page.gamingOn ? "on" : "off")
                            accent: page.gamingOn; dot: page.gamingOn
                        }
                        Badge {
                            text: "Flow " + (page.flowOn ? "on" : "off")
                            accent: page.flowOn; dot: page.flowOn
                        }
                    }
                }
            }

            // ---- Radial preview + button map ----
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap

                GlassCard {
                    id: radialCard
                    Layout.preferredWidth: 300
                    Layout.preferredHeight: 300
                    scale: radMa.containsMouse ? 1.015 : 1.0
                    Behavior on scale { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }
                    Column {
                        anchors.fill: parent; anchors.margins: Theme.padCard
                        spacing: Theme.gapS
                        CardHeader {
                            width: parent.width
                            title: "Radial menu"; subtitle: "Your eight thumb actions"
                            icon: "image://icon/" + Theme.accent.toString().slice(1) + "/view-grid-symbolic"
                            Badge { text: "Edit" }
                        }
                        Item {
                            id: ringBox
                            width: parent.width
                            height: parent.height - 56
                            readonly property real rr: Math.min(width, height) * 0.36
                            Image {
                                anchors.centerIn: parent
                                width: Math.min(parent.width, parent.height)
                                height: width
                                source: Theme.wheelImage(page.wheelKey)
                                sourceSize.width: 512; sourceSize.height: 512
                                fillMode: Image.PreserveAspectFit; smooth: true
                            }
                            Repeater {
                                model: Slices
                                Item {
                                    required property int index
                                    required property string icon
                                    required property string hex
                                    required property string actionId
                                    property string btnImg: page.mono ? "" : Theme.sliceButton(actionId)
                                    width: 34; height: 34
                                    x: ringBox.width / 2 + ringBox.rr * Math.cos((index * 45 - 90) * Math.PI / 180) - width / 2
                                    y: ringBox.height / 2 + ringBox.rr * Math.sin((index * 45 - 90) * Math.PI / 180) - height / 2
                                    Image {
                                        anchors.fill: parent; visible: btnImg !== ""
                                        source: btnImg; sourceSize.width: 128; sourceSize.height: 128
                                        smooth: true; fillMode: Image.PreserveAspectFit
                                    }
                                    ActionIcon {
                                        anchors.centerIn: parent; visible: btnImg === ""
                                        iconName: icon; tint: hex; px: 18
                                    }
                                }
                            }
                        }
                    }
                    MouseArea {
                        id: radMa; anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Backend.goTo("buttons")
                    }
                }

                GlassCard {
                    id: bmapCard
                    Layout.fillWidth: true
                    Layout.preferredHeight: 300
                    scale: bmMa.containsMouse ? 1.012 : 1.0
                    Behavior on scale { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }
                    Column {
                        anchors.fill: parent; anchors.margins: Theme.padCard
                        spacing: 2
                        CardHeader {
                            width: parent.width
                            title: "Button map"; subtitle: "Current physical button actions"
                            icon: "image://icon/" + Theme.accent.toString().slice(1) + "/input-mouse-symbolic"
                            Badge { text: "Edit" }
                        }
                        Item { width: 1; height: 4 }
                        Rectangle { width: parent.width; height: 1; color: Theme.border }
                        Repeater {
                            model: Backend.buttonSlots()
                            Item {
                                required property var modelData
                                required property int index
                                width: parent.width; height: 32
                                Text {
                                    anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.name; color: Theme.textBody
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                                }
                                Rectangle {
                                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                                    radius: 7; color: Theme.accentSubtle
                                    implicitWidth: actT.implicitWidth + 18; height: 24
                                    Text {
                                        id: actT; anchors.centerIn: parent
                                        text: page.actionName(modelData.slot, modelData.default)
                                        color: Theme.accent
                                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
                                    }
                                }
                                Rectangle {
                                    anchors.bottom: parent.bottom; width: parent.width; height: 1
                                    color: Theme.border; visible: index < 6
                                }
                            }
                        }
                    }
                    MouseArea {
                        id: bmMa; anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Backend.goTo("buttons")
                    }
                }
            }

            // ---- System ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: sysCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: sysCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    SectionHeader { text: "System" }
                    Flow {
                        width: parent.width
                        spacing: Theme.gapL
                        Repeater {
                            model: [
                                { l: "Daemon", v: Backend.daemonVersion },
                                { l: "App", v: Backend.appVersion },
                                { l: "Device mode", v: Backend.deviceMode }
                            ]
                            Row {
                                required property var modelData
                                spacing: 6
                                Text {
                                    text: modelData.l; color: Theme.textMuted
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: modelData.v; color: Theme.textBody
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                    font.weight: Font.DemiBold
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
