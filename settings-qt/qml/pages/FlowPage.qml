import QtQuick
import QtQuick.Layouts
import "../components"

// Flow: move the cursor and share the clipboard between nearby computers.
// Logitech-only; the behaviour controls dim while the master switch is off.
Item {
    id: root
    anchors.fill: parent

    readonly property string _accent: Theme.accent.toString().slice(1)

    // Mirrors flow.enabled; gates the behaviour card and the off-state intro.
    property bool flowOn: Backend.get("flow.enabled", false)

    // A SettingRow with a subtle hover wash behind it. Children sit on top, so
    // their own controls keep their clicks; hovering the label area lights it up.
    component HoverRow: Item {
        id: hr
        default property alias body: bodyHolder.data
        width: parent ? parent.width : 0
        height: bodyHolder.childrenRect.height
        Rectangle {
            anchors.fill: parent
            anchors.leftMargin: -Theme.gapS; anchors.rightMargin: -Theme.gapS
            anchors.topMargin: 1; anchors.bottomMargin: 1
            radius: Theme.radiusCtl
            color: hovMa.containsMouse ? "#0AFFFFFF" : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.dShort } }
        }
        MouseArea {
            id: hovMa
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
        }
        Item {
            id: bodyHolder
            anchors.left: parent.left; anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            height: childrenRect.height
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

            // ---- Master switch (+ off-state intro) ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: masterCol.implicitHeight + Theme.padCard * 2
                Column {
                    id: masterCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Flow"
                        subtitle: "Move the cursor and copy between nearby computers"
                        icon: "image://icon/" + root._accent + "/" + Theme.iconStyle + "/flow"
                        Toggle {
                            checked: Backend.get("flow.enabled", false)
                            onToggled: (v) => { Backend.setLocal("flow.enabled", v); root.flowOn = v }
                        }
                    }
                    // Intro art + value prop, shown only while Flow is off.
                    Rectangle {
                        width: parent.width; height: 1; color: Theme.border
                        visible: !root.flowOn
                    }
                    RowLayout {
                        width: parent.width
                        visible: !root.flowOn
                        spacing: Theme.pad
                        SpotImage { name: "spot_flow"; size: 104; Layout.alignment: Qt.AlignVCenter }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            spacing: Theme.gapS
                            Text {
                                Layout.fillWidth: true
                                text: "Move your cursor and clipboard between nearby computers."
                                color: Theme.textBody
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                                font.weight: Font.Medium
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "Turn Flow on to pick the handoff edge and share what you copy."
                                color: Theme.textMuted
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }

            // ---- Generic-device note (instead of the behaviour card) ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: 64
                visible: Backend.isGeneric
                Row {
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: Theme.pad; anchors.rightMargin: Theme.pad
                    spacing: Theme.gapS
                    ActionIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        iconName: "dialog-information-symbolic"; tint: Theme.textMuted; px: 18
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Flow requires a Logitech device"
                        color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                        font.weight: Font.Medium
                    }
                }
            }

            // ---- Behaviour ----
            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: behaveCol.implicitHeight + Theme.padCard * 2
                visible: !Backend.isGeneric
                opacity: root.flowOn ? 1.0 : 0.5
                enabled: root.flowOn
                Behavior on opacity { NumberAnimation { duration: Theme.dMed } }
                Column {
                    id: behaveCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: "Behaviour"
                        subtitle: "When and how the cursor crosses to the next machine"
                        icon: "image://icon/" + root._accent + "/" + Theme.iconStyle + "/preferences-system-symbolic"
                    }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Switch edge"
                        desc: "Which screen edge hands off to the next computer"
                        SegmentedControl {
                            width: 300
                            model: [{ id: "left", name: "Left" }, { id: "right", name: "Right" },
                                    { id: "top", name: "Top" }, { id: "bottom", name: "Bottom" }]
                            currentId: Backend.get("flow.direction", "left")
                            onActivated: (id) => Backend.setLocal("flow.direction", id)
                    }
                        }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Move cursor to edge to switch"
                        desc: "Cross over by pushing the pointer past the edge"
                        Toggle {
                            checked: Backend.get("flow.edge_trigger", true)
                            onToggled: (v) => Backend.setLocal("flow.edge_trigger", v)
                    }
                        }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Share clipboard"
                        desc: "Copy on one computer, paste on the other"
                        Toggle {
                            checked: Backend.get("flow.share_clipboard", true)
                            onToggled: (v) => Backend.setLocal("flow.share_clipboard", v)
                    }
                        }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Edge sensitivity"
                        desc: "How firmly you must push to cross over"
                        Slider {
                            width: 240; from: 0; to: 100; showValue: true; suffix: "%"
                            value: Backend.get("flow.edge_sensitivity", 50)
                            onCommitted: (v) => Backend.setLocal("flow.edge_sensitivity", Math.round(v))
                    }
                        }
                    Rectangle { width: parent.width; height: 1; color: Theme.border }
                    SettingRow {
                        label: "Monitor"
                        desc: "Which display the handoff edge belongs to"
                        ComboBox {
                            width: 180
                            model: [{ id: "", name: "Auto" }]
                            currentId: Backend.get("flow.monitor", "")
                            onActivated2: (id) => Backend.setLocal("flow.monitor", id)
                    }
                        }
                }
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
