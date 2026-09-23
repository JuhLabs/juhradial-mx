import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import "../components"

// Landing dashboard: the device on a lit stage, one instrument strip of live
// readouts, the radial preview and the button map. No hero-metric tiles, no
// hover scaling: hover lifts a border, light means state.
Item {
    id: page
    anchors.fill: parent

    // Config-derived values have no NOTIFY, so refresh them on live updates.
    property string wheelMode: Backend.get("scroll.mode", "smartshift")
    property bool gamingOn: Backend.get("gaming.enabled", false)
    property bool flowOn: Backend.get("flow.enabled", false)

    function _cap(s) { return s.length ? s.charAt(0).toUpperCase() + s.slice(1) : s }

    property var actMap: ({})
    property string wheelKey: Backend.get("radial.wheel", "none")
    readonly property bool mono: Theme.iconStyle === "mono"
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
            page.wheelKey = Backend.get("radial.wheel", "none")
        }
    }

    // One readout cell of the instrument strip: icon, mono value, muted label.
    component Instrument: Item {
        id: cell
        property string icon: ""
        property string value: ""
        property string label: ""
        property string toTab: ""
        property bool live: false
        property bool last: false
        Layout.fillWidth: true
        Layout.preferredHeight: 72
        Rectangle {
            anchors.fill: parent; anchors.margins: 6
            radius: Theme.radiusCtl
            color: cellMa.containsMouse ? "#12FFFFFF" : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.dShort } }
        }
        Row {
            anchors.left: parent.left; anchors.leftMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12
            Rectangle {
                width: 34; height: 34; radius: 10
                anchors.verticalCenter: parent.verticalCenter
                color: cell.live ? Theme.accentSubtle : "#12FFFFFF"
                border.width: 1; border.color: cell.live ? Theme.accentFaint : Theme.border
                ActionIcon {
                    anchors.centerIn: parent
                    iconName: cell.icon; px: 18
                    tint: cell.live ? Theme.accent : Theme.textBody
                }
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    text: cell.value; color: Theme.textPrimary
                    font.family: Theme.fontMono; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                }
                Text {
                    text: cell.label; color: Theme.textMuted
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                }
            }
        }
        Rectangle {
            visible: !cell.last
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            width: 1; height: parent.height - 28; color: Theme.border
        }
        MouseArea {
            id: cellMa; anchors.fill: parent; hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: if (cell.toTab !== "") Backend.goTo(cell.toTab)
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

            // ---- Hero: the device on a lit stage ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: 176
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.pad
                    spacing: Theme.pad

                    Item {
                        Layout.preferredWidth: 210; Layout.preferredHeight: 134
                        Layout.alignment: Qt.AlignVCenter
                        // stage: a soft accent pool under the device (light is state:
                        // it only glows while the daemon is connected)
                        Shape {
                            anchors.centerIn: parent
                            width: 230; height: 90
                            y: parent.height - 62
                            opacity: Backend.daemonAvailable ? 1 : 0.35
                            Behavior on opacity { NumberAnimation { duration: Theme.dLong } }
                            ShapePath {
                                strokeWidth: 0
                                fillGradient: RadialGradient {
                                    centerX: 115; centerY: 45; centerRadius: 115
                                    focalX: 115; focalY: 45
                                    GradientStop { position: 0.0; color: Backend.daemonAvailable ? Theme.accentSubtle : "#20FFFFFF" }
                                    GradientStop { position: 0.6; color: "#00000000" }
                                }
                                startX: 0; startY: 45
                                PathArc { x: 230; y: 45; radiusX: 115; radiusY: 45 }
                                PathArc { x: 0; y: 45; radiusX: 115; radiusY: 45 }
                            }
                        }
                        Image {
                            anchors.centerIn: parent
                            readonly property bool mx3: Backend.deviceName.indexOf("MX Master 3") >= 0
                            source: assetsDir + (mx3 ? "/devices/mx3_quarter.png" : "/devices/mx4_side.png")
                            sourceSize.width: mx3 ? 549 : 1289; sourceSize.height: mx3 ? 804 : 829
                            width: mx3 ? 96 : 200; height: mx3 ? 140 : 128
                            fillMode: Image.PreserveAspectFit
                            smooth: true; asynchronous: true
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignVCenter
                        spacing: Theme.gapS
                        Text {
                            text: Backend.deviceName
                            color: Theme.textPrimary
                            font.family: Theme.fontDisplay; font.pixelSize: Theme.fsH1; font.weight: Font.DemiBold
                            Layout.fillWidth: true; elide: Text.ElideRight
                        }
                        Row {
                            spacing: Theme.gapS
                            Badge {
                                text: Backend.daemonAvailable ? "Connected" : "Daemon offline"
                                accent: Backend.daemonAvailable
                                dot: true
                            }
                            Badge { visible: !Backend.isGeneric; text: "HID++ " + Backend.deviceMode }
                            Badge { visible: Backend.numHosts > 1; text: "Host " + (Backend.currentHost + 1) + " of " + Backend.numHosts }
                        }
                        Text {
                            text: Backend.daemonAvailable
                                  ? "Gesture button, thumb wheel and haptics ready."
                                  : "Start the JuhRadial daemon to control this device."
                            color: Theme.textMuted
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                            Layout.fillWidth: true; elide: Text.ElideRight
                        }
                    }

                    BatteryRing {
                        percent: Backend.battery
                        charging: Backend.charging
                        size: 118
                        Layout.alignment: Qt.AlignVCenter
                    }
                }
            }

            // ---- Instrument strip: every live readout in one card ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: 74
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 1
                    spacing: 0
                    Instrument { icon: "input-mouse-symbolic"; value: Backend.dpi; label: "DPI"; toTab: "scroll" }
                    Instrument {
                        icon: "view-list-symbolic"
                        value: page._cap(Backend.wheelMode !== "" ? Backend.wheelMode : page.wheelMode)
                        label: "Wheel mode"; toTab: "scroll"
                    }
                    Instrument {
                        icon: "audio-volume-medium-symbolic"
                        value: Backend.hapticsEnabled ? "On" : "Off"; label: "Haptics"
                        live: Backend.hapticsEnabled; toTab: "haptics"
                    }
                    Instrument {
                        icon: "easy-switch"
                        value: (Backend.currentHost + 1) + " / " + Math.max(1, Backend.numHosts)
                        label: "Easy-Switch host"; live: Backend.numHosts > 1; toTab: "easyswitch"
                    }
                    Instrument {
                        icon: "applications-development-symbolic"
                        value: page.gamingOn ? "On" : "Off"; label: "Gaming mode"
                        live: page.gamingOn; toTab: "gaming"
                    }
                    Instrument {
                        icon: "view-dual-symbolic"
                        value: page.flowOn ? "On" : "Off"; label: "Flow"
                        live: page.flowOn; toTab: "flow"; last: true
                    }
                }
            }

            // ---- Radial preview + button map ----
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap

                GlassCard {
                    id: radialCard
                    Layout.preferredWidth: 310
                    Layout.preferredHeight: 312
                    Column {
                        anchors.fill: parent; anchors.margins: Theme.padCard
                        spacing: Theme.gapS
                        CardHeader {
                            width: parent.width
                            title: "Radial menu"; subtitle: "Your eight thumb actions"
                            icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/view-grid-symbolic"
                            Badge { text: "Edit"; accent: radMa.containsMouse }
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
                                visible: page.wheelKey !== "none"
                                source: page.wheelKey !== "none" ? Theme.wheelImage(page.wheelKey) : ""
                                sourceSize.width: 512; sourceSize.height: 512
                                fillMode: Image.PreserveAspectFit; smooth: true
                            }
                            ClassicWheel {
                                anchors.centerIn: parent
                                visible: page.wheelKey === "none"
                                size: Math.min(parent.width, parent.height)
                            }
                            Repeater {
                                model: Slices
                                Item {
                                    required property int index
                                    required property string icon
                                    required property string hex
                                    required property string actionId
                                    property string btnImg: (page.mono || icon.startsWith("/")) ? "" : (Theme.iconStyle, Theme.sliceButton(actionId))
                                    width: 36; height: 36
                                    x: ringBox.width / 2 + ringBox.rr * Math.cos((index * 45 - 90) * Math.PI / 180) - width / 2
                                    y: ringBox.height / 2 + ringBox.rr * Math.sin((index * 45 - 90) * Math.PI / 180) - height / 2
                                    Image {
                                        anchors.fill: parent; visible: btnImg !== ""
                                        source: btnImg; sourceSize.width: 128; sourceSize.height: 128
                                        smooth: true; fillMode: Image.PreserveAspectFit
                                    }
                                    Rectangle {
                                        anchors.fill: parent; radius: width / 2
                                        visible: btnImg === ""
                                        color: "#1B1F28"; border.width: 1.5
                                        border.color: page.mono ? Theme.borderStrong : hex
                                    }
                                    ActionIcon {
                                        anchors.centerIn: parent; visible: btnImg === ""
                                        iconName: icon; tint: page.mono ? Theme.textBody : hex; px: 18
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
                    Layout.preferredHeight: 312
                    Column {
                        anchors.fill: parent; anchors.margins: Theme.padCard
                        spacing: 2
                        CardHeader {
                            width: parent.width
                            title: "Button map"; subtitle: "Current physical button actions"
                            icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/input-mouse-symbolic"
                            Badge { text: "Edit"; accent: bmMa.containsMouse }
                        }
                        Item { width: 1; height: 4 }
                        Rectangle { width: parent.width; height: 1; color: Theme.border }
                        Repeater {
                            model: Backend.buttonSlots()
                            Item {
                                id: mapRow
                                required property var modelData
                                required property int index
                                width: parent.width; height: 32
                                Rectangle {
                                    anchors.fill: parent; anchors.leftMargin: -8; anchors.rightMargin: -8
                                    radius: 8; color: rowHov.hovered ? "#0CFFFFFF" : "transparent"
                                }
                                HoverHandler { id: rowHov }
                                Text {
                                    anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.name; color: Theme.textBody
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                                }
                                Rectangle {
                                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                                    radius: 7; color: Theme.accentSubtle
                                    border.width: 1; border.color: Theme.accentFaint
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
                Layout.preferredHeight: sysRow.implicitHeight + Theme.padCard * 2
                Flow {
                    id: sysRow
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: Theme.padCard
                    spacing: Theme.gapL
                    Repeater {
                        model: [
                            { l: "Daemon", v: Backend.daemonVersion },
                            { l: "App", v: Backend.appVersion },
                            { l: "Device mode", v: Backend.deviceMode },
                            { l: "Theme", v: Theme.name }
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
                                font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                                font.weight: Font.DemiBold
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
