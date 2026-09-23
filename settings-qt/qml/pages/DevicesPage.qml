import QtQuick
import QtQuick.Layouts
import "../components"

// Device overview: hero, live status tiles and system info.
Item {
    id: page
    anchors.fill: parent

    readonly property string _ic: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/"

    // Muted label (left) + bold value (right) line. Values bind to live props.
    component StatusRow: Item {
        id: sr
        property string label: ""
        property string value: ""
        width: parent ? parent.width : 0
        height: 42
        Text {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            text: sr.label; color: Theme.textMuted
            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
        }
        Text {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            text: sr.value; color: Theme.textPrimary
            font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
        }
    }

    // Inset metric tile: icon chip + value + label. Values bind to live props.
    component MetricTile: Rectangle {
        id: mt
        property string icon: ""
        property string value: ""
        property string label: ""
        property color valueColor: Theme.textPrimary
        radius: Theme.radiusCtl
        color: "#10FFFFFF"
        border.width: 1
        border.color: Theme.border
        implicitHeight: 74
        Row {
            anchors.fill: parent
            anchors.leftMargin: 14; anchors.rightMargin: 14
            spacing: Theme.gapS + 2
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 42; height: 42; radius: 11
                color: Theme.accentSubtle
                ActionIcon {
                    anchors.centerIn: parent
                    iconName: mt.icon; tint: Theme.accent; px: 20
                }
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    text: mt.value; color: mt.valueColor
                    font.family: Theme.fontMono; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                }
                Text {
                    text: mt.label; color: Theme.textMuted
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                }
            }
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

            // ---- Generic banner ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: 66
                visible: Backend.isGeneric
                Row {
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Theme.pad; anchors.rightMargin: Theme.pad
                    spacing: Theme.gapS
                    ActionIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        iconName: "dialog-information-symbolic"; tint: Theme.textMuted; px: 20
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Generic mouse mode: Logitech features are unavailable"
                        color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium
                    }
                }
            }

            // ---- Connected devices roster ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: rosterCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: rosterCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Connected devices"; subtitle: "Everything the daemon is talking to right now"
                        icon: page._ic + "devices"
                        IconButton {
                            icon: "view-refresh-symbolic"; tint: Theme.textMuted; diameter: 32
                            onClicked: { Backend.refreshDevices(); kbCard.reload() }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }

                    // mouse row
                    Item {
                        width: parent.width; height: 84
                        RowLayout {
                            anchors.fill: parent
                            spacing: Theme.gapL
                            Item {
                                Layout.preferredWidth: 104; Layout.preferredHeight: 70
                                Image {
                                    anchors.centerIn: parent
                                    source: assetsDir + "/devices/mx4_side.png"
                                    sourceSize.width: 1289; sourceSize.height: 829
                                    width: 104; height: 67
                                    fillMode: Image.PreserveAspectFit; smooth: true; asynchronous: true
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 4
                                Text {
                                    text: Backend.deviceName; color: Theme.textPrimary
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                                    Layout.fillWidth: true; elide: Text.ElideRight
                                }
                                Row {
                                    spacing: Theme.gapS
                                    Badge {
                                        text: Backend.isGeneric ? "Generic HID" : "USB receiver"
                                        dot: true; accent: !Backend.isGeneric
                                    }
                                    Badge { text: Backend.deviceMode }
                                    Badge {
                                        visible: !Backend.isGeneric
                                        text: "Host " + (Backend.currentHost + 1) + " of " + Backend.numHosts
                                    }
                                }
                            }
                            Column {
                                Layout.alignment: Qt.AlignVCenter
                                spacing: 2
                                Text {
                                    anchors.right: parent.right
                                    text: Backend.battery + "%"; color: Theme.textPrimary
                                    font.family: Theme.fontMono; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                                }
                                Text {
                                    anchors.right: parent.right
                                    text: Backend.charging ? "charging" : "battery"; color: Theme.textMuted
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                }
                            }
                        }
                    }

                    // keyboard row (beta)
                    Rectangle { width: parent.width; height: 1; color: Theme.border; visible: kbCard.kb.enabled }
                    Item {
                        width: parent.width; height: 72
                        visible: kbCard.kb.enabled
                        RowLayout {
                            anchors.fill: parent
                            spacing: Theme.gapL
                            Item {
                                Layout.preferredWidth: 104; Layout.preferredHeight: 60
                                Rectangle {
                                    anchors.centerIn: parent
                                    width: 54; height: 54; radius: 14
                                    color: kbCard.kb.present ? Theme.accentSubtle : "#12FFFFFF"
                                    border.width: 1; border.color: kbCard.kb.present ? Theme.accentFaint : Theme.border
                                    ActionIcon {
                                        anchors.centerIn: parent
                                        iconName: "keyboard"; px: 26
                                        tint: kbCard.kb.present ? Theme.accent : Theme.textMuted
                                    }
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 4
                                Text {
                                    text: kbCard.kb.present ? "MX Keys S" : "MX Keys S (not detected)"
                                    color: kbCard.kb.present ? Theme.textPrimary : Theme.textMuted
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                                    Layout.fillWidth: true; elide: Text.ElideRight
                                }
                                Row {
                                    spacing: Theme.gapS
                                    Badge { text: "Beta" }
                                    Badge {
                                        visible: kbCard.kb.present
                                        text: kbCard.kb.sleeping ? "Asleep, press a key" : "Awake"
                                        dot: true; accent: kbCard.kb.present && !kbCard.kb.sleeping
                                    }
                                    Badge { visible: kbCard.kb.present && kbCard.kb.charging; text: "Charging"; accent: true }
                                }
                            }
                            Column {
                                Layout.alignment: Qt.AlignVCenter
                                spacing: 2
                                visible: kbCard.kb.present
                                Text {
                                    anchors.right: parent.right
                                    text: kbCard.kb.sleeping ? "--" : kbCard.kb.battery + "%"; color: Theme.textPrimary
                                    font.family: Theme.fontMono; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                                }
                                Text {
                                    anchors.right: parent.right
                                    text: "battery"; color: Theme.textMuted
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                                }
                            }
                        }
                    }
                }
            }

            // ---- Device mode ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: dmCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: dmCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Device mode"; subtitle: "Override automatic device detection"
                        icon: page._ic + "preferences-system-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Force generic mode"
                        desc: "Treat this as a standard HID mouse and hide Logitech-only tabs"
                        Toggle {
                            checked: Backend.get("device_mode", "auto") === "generic"
                            onToggled: (v) => Backend.setDeviceMode(v ? "generic" : "auto")
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border
                                visible: Backend.isGeneric }
                    SettingRow {
                        visible: Backend.isGeneric
                        label: "Radial trigger button"
                        desc: "Which button opens the radial menu on a generic mouse"
                        ComboBox {
                            width: 220
                            model: Backend.genericTriggerOptions()
                            currentId: Backend.genericTrigger
                            onActivated2: (id) => Backend.setGenericTrigger(id)
                        }
                    }
                }
            }

            // ---- Keyboard (beta) ----
            GlassCard {
                id: kbCard
                Layout.fillWidth: true
                Layout.preferredHeight: kbCol.implicitHeight + Theme.padCard * 2
                property var kb: ({ present: false, enabled: false, battery: 0, charging: false, sleeping: false, keyCount: 0 })
                function reload() { kb = Backend.keyboardInfo() }
                Component.onCompleted: reload()
                // Daemon needs a moment to reload config and query the keyboard
                // over HID++ after the enable toggle; then refresh the card.
                Timer { id: kbReload; interval: 1200; onTriggered: kbCard.reload() }
                Column {
                    id: kbCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Keyboard"
                        subtitle: "MX Keys S backlight over HID++, plus generic keyboards"
                        icon: page._ic + "keyboard"
                        Badge { text: "Beta" }
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "MX Keys S support"
                        desc: "Query battery and control backlight over HID++"
                        Toggle {
                            checked: kbCard.kb.enabled
                            onToggled: (v) => {
                                Backend.set("keyboard.mx_keys.enabled", v)
                                kbReload.restart()
                            }
                        }
                    }
                    Text {
                        visible: kbCard.kb.enabled && !kbCard.kb.present
                        width: parent.width
                        text: "No compatible keyboard detected yet. Connect an MX Keys S (Bolt receiver or Bluetooth); the card refreshes when you reopen this page."
                        color: Theme.textMuted; wrapMode: Text.WordWrap
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border
                                visible: kbCard.kb.present }
                    SettingRow {
                        visible: kbCard.kb.present
                        label: "Backlight"
                        desc: "Backlight brightness (8 levels, manual mode)"
                        Slider {
                            width: 200; from: 0; to: 100; showValue: true; suffix: "%"
                            value: 50
                            onCommitted: (v) => Backend.setKeyboardBacklight(Math.round(v))
                        }
                    }
                    Text {
                        visible: kbCard.kb.present && kbCard.kb.keyCount > 0
                        width: parent.width
                        text: kbCard.kb.keyCount + " keys available for generic remapping"
                        color: Theme.textMuted; wrapMode: Text.WordWrap
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                    }
                }
            }

            // ---- Status ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: stCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: stCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Status"; subtitle: "Live device state"
                        icon: page._ic + "dashboard"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    GridLayout {
                        width: parent.width
                        columns: 2
                        columnSpacing: Theme.gapS
                        rowSpacing: Theme.gapS
                        MetricTile {
                            Layout.fillWidth: true
                            icon: Backend.charging ? "battery-full-charging-symbolic" : "battery-good-symbolic"
                            value: Backend.battery + "%"
                            label: Backend.charging ? "Charging" : "Battery"
                        }
                        MetricTile {
                            Layout.fillWidth: true
                            icon: "input-mouse-symbolic"
                            value: Backend.dpi + " DPI"
                            label: "Pointer speed"
                        }
                        MetricTile {
                            Layout.fillWidth: true
                            icon: "network-wireless-symbolic"
                            value: (Backend.currentHost + 1) + " / " + Backend.numHosts
                            label: "Active host"
                        }
                        MetricTile {
                            Layout.fillWidth: true
                            icon: "view-list-symbolic"
                            value: Backend.wheelMode === "smartshift" ? "SmartShift"
                                 : Backend.wheelMode === "freespin" ? "Free-spin"
                                 : Backend.wheelMode === "ratchet" ? "Ratchet"
                                 : (Backend.ratchet ? "Ratchet" : "Free-spin")
                            label: "Scroll wheel"
                        }
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
                    CardHeader {
                        width: parent.width
                        title: "System"; subtitle: "Versions and supported features"
                        icon: page._ic + "applications-system-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    StatusRow { label: "Daemon version"; value: Backend.daemonVersion }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    StatusRow { label: "App version"; value: Backend.appVersion }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    Item {
                        width: parent.width
                        height: capCol.implicitHeight + 16
                        Column {
                            id: capCol
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Theme.gapS
                            SectionHeader { text: "Capabilities" }
                            Row {
                                spacing: Theme.gapS
                                Badge { text: "SmartShift"; dot: true; accent: Backend.smartShiftSupported }
                                Badge { text: "Thumb wheel"; dot: true; accent: Backend.thumbwheelSupported }
                                Badge { text: "Haptics"; dot: true; accent: !Backend.isGeneric }
                            }
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }

    // Live status props already NOTIFY via liveChanged; this keeps them fresh.
    Connections { target: Backend; function onLiveChanged() {} }
}
