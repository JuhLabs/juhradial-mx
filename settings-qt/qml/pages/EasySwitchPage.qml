import QtQuick
import QtQuick.Layouts
import "../components"

// Easy-Switch: the mouse's computer slots (paired or empty, how, and which
// one is this computer), switching with a confirmation that names the way
// back, this computer's name, taking the keyboard along, and the ring's
// Easy-Switch submenu.
Item {
    id: page
    anchors.fill: parent

    property int bump: 0
    property int confirmSlot: -1
    Connections {
        target: Backend
        function onConfigChanged() { page.bump++ }
    }
    Component.onCompleted: Backend.readHostSlots()

    function cfg(path, def) { page.bump; return Backend.get(path, def) }
    readonly property int count: Math.max(1, Backend.numHosts)
    readonly property bool keyboardOn: cfg("keyboard.mx_keys.enabled", false)
    readonly property var slots: Backend.hostSlots
    function slotAt(i) {
        if (i < slots.length) return slots[i]
        var n = Backend.hostNames[i] || ""
        return { index: i, paired: n !== "", bus: "", name: n, unknown: true }
    }
    function nameOf(i) {
        var s = slotAt(i)
        if (i === Backend.currentHost && Backend.localHostAlias !== "") return Backend.localHostAlias
        return s.name !== "" ? s.name : qsTr("Computer %1").arg(i + 1)
    }
    function facts(s) {
        if (s.unknown) return s.paired ? qsTr("Paired") : qsTr("Status not available yet")
        if (!s.paired) return qsTr("Empty. Hold the Easy-Switch button for 3 seconds to pair a computer here")
        if (s.bus === "bluetooth") return qsTr("Paired over Bluetooth")
        if (s.bus === "receiver") return qsTr("Paired with a USB receiver")
        return qsTr("Paired")
    }

    component Divider: Rectangle { width: parent ? parent.width : 400; height: 1; color: Theme.border }

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
                Layout.preferredHeight: hostCol.implicitHeight + Theme.padCard * 2
                visible: !Backend.isGeneric
                Column {
                    id: hostCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    CardHeader {
                        width: parent.width
                        title: qsTr("Computers")
                        subtitle: qsTr("The mouse remembers up to %n computer(s). Its Easy-Switch button, or Switch here, moves it between them", "", page.count)
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/easyswitch"
                        IconButton {
                            icon: "view-refresh-symbolic"; tint: Theme.textMuted; diameter: 30
                            tip: qsTr("Read the slots again")
                            onClicked: { Backend.refreshDevices(); Backend.readHostSlots() }
                        }
                    }
                    Divider {}
                    Repeater {
                        model: page.count
                        Rectangle {
                            id: row
                            required property int index
                            readonly property var s: page.slotAt(index)
                            readonly property bool here: Backend.currentHost === index
                            readonly property bool asking: page.confirmSlot === index
                            width: hostCol.width
                            height: rowCol.implicitHeight + 20
                            radius: Theme.radiusCtl
                            color: here ? Theme.accentSubtle : "transparent"
                            border.width: 1; border.color: here ? Theme.accentFaint : Theme.border
                            activeFocusOnTab: true
                            Accessible.role: Accessible.ListItem
                            Accessible.name: page.nameOf(index) + (here ? qsTr(", this computer") : "") + ". " + page.facts(s)
                            FocusHalo { active: row.activeFocus; radius: Theme.radiusCtl }
                            Column {
                                id: rowCol
                                anchors.left: parent.left; anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 14; anchors.rightMargin: 10
                                spacing: 8
                                RowLayout {
                                    width: parent.width
                                    spacing: Theme.gapS
                                    Rectangle {
                                        Layout.preferredWidth: 30; Layout.preferredHeight: 30; radius: 15
                                        color: row.here ? Theme.accent : "#14FFFFFF"
                                        border.width: 1; border.color: row.here ? Theme.accent : Theme.border
                                        Text { anchors.centerIn: parent; text: String(row.index + 1)
                                               color: row.here ? "#FFFFFF" : Theme.textBody
                                               font.family: Theme.fontMono; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold }
                                    }
                                    Column {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text {
                                            text: row.here ? qsTr("%1 (this computer)").arg(page.nameOf(row.index)) : page.nameOf(row.index)
                                            color: row.s.paired || row.here ? Theme.textPrimary : Theme.textMuted
                                            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
                                        }
                                        Text {
                                            width: parent.width; wrapMode: Text.WordWrap
                                            text: page.facts(row.s)
                                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                        }
                                    }
                                    Column {
                                        spacing: 2
                                        Text { text: qsTr("Icon in radial menu"); color: Theme.textMuted
                                               font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro }
                                        ComboBox {
                                            width: 150
                                            accessibleName: qsTr("Icon in radial menu for %1").arg(page.nameOf(row.index))
                                            model: Backend.easySwitchOs()
                                            currentId: (page.cfg("radial_menu.easy_switch_host_os", []) || [])[row.index] || "unknown"
                                            onActivated2: (id) => Backend.setHostOs(row.index, id)
                                        }
                                    }
                                    PrimaryButton {
                                        visible: !row.here
                                        enabled: row.s.paired && !row.asking
                                        text: qsTr("Switch"); ghost: true
                                        onClicked: page.confirmSlot = row.index
                                    }
                                }
                                // Confirm: this computer loses its pointer, so say how to come back.
                                Rectangle {
                                    visible: row.asking
                                    width: parent.width; height: askRow.implicitHeight + 16
                                    radius: Theme.radiusCtl; color: "#12FFFFFF"
                                    RowLayout {
                                        id: askRow
                                        anchors.left: parent.left; anchors.right: parent.right
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.leftMargin: 12; anchors.rightMargin: 8
                                        spacing: Theme.gapS
                                        Text {
                                            Layout.fillWidth: true; wrapMode: Text.WordWrap
                                            text: qsTr("The mouse leaves this computer. To come back, press the button under the mouse until light %1 is on.").arg(Backend.currentHost + 1)
                                            color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                        }
                                        PrimaryButton { text: qsTr("Cancel"); ghost: true; onClicked: page.confirmSlot = -1 }
                                        PrimaryButton {
                                            text: qsTr("Switch to %1").arg(page.nameOf(row.index))
                                            onClicked: { page.confirmSlot = -1; Backend.switchHost(row.index) }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: meCol.implicitHeight + Theme.padCard * 2
                visible: !Backend.isGeneric
                Column {
                    id: meCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: Theme.gapS
                    SettingRow {
                        label: qsTr("This computer's name")
                        desc: qsTr("How this computer shows on this page. The mouse calls it %1").arg(Backend.hostNames[Backend.currentHost] || qsTr("nothing yet"))
                        InputField {
                            width: 240
                            accessibleName: qsTr("This computer's name")
                            placeholder: Backend.hostNames[Backend.currentHost] || qsTr("Name")
                            text: Backend.localHostAlias
                            onEditingFinished: Backend.setLocalHostAlias(text)
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Move the keyboard too")
                        desc: page.keyboardOn
                              ? qsTr("When the mouse switches, your MX Keys follows to the same computer, matched by name. If the keyboard is asleep it follows when you next touch it")
                              : qsTr("Turn on keyboard support on the Devices tab first")
                        Row {
                            spacing: Theme.gapS
                            PrimaryButton {
                                visible: !page.keyboardOn
                                text: qsTr("Devices"); ghost: true
                                onClicked: Backend.goTo("devices")
                            }
                            Toggle {
                                anchors.verticalCenter: parent.verticalCenter
                                enabled: page.keyboardOn
                                checked: page.cfg("keyboard.mx_keys.move_together", false)
                                onToggled: (v) => Backend.set("keyboard.mx_keys.move_together", v)
                            }
                        }
                    }
                    Divider {}
                    SettingRow {
                        label: qsTr("Easy-Switch in the radial menu")
                        desc: qsTr("Slice 6 (%1) becomes a submenu of your computers").arg(
                                  (page.bump, Slices.sliceAt(5).label) || qsTr("empty"))
                        Toggle {
                            checked: page.cfg("radial_menu.easy_switch_shortcuts", false)
                            onToggled: (v) => Backend.setLocal("radial_menu.easy_switch_shortcuts", v)
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: howCol.implicitHeight + Theme.padCard * 2
                visible: !Backend.isGeneric
                Column {
                    id: howCol
                    anchors.fill: parent; anchors.margins: Theme.padCard
                    spacing: 6
                    CardHeader {
                        width: parent.width
                        title: qsTr("How Easy-Switch works")
                        icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/help-about-symbolic"
                    }
                    Repeater {
                        model: [qsTr("Press the button under the mouse to step to the next computer; its light shows which one."),
                                qsTr("Hold it for 3 seconds to pair a new computer in that slot (its light blinks)."),
                                qsTr("Each computer names its slot when it pairs, which is where the names above come from.")]
                        Text {
                            required property string modelData
                            width: howCol.width; wrapMode: Text.WordWrap
                            text: modelData
                            color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                    }
                }
            }

            EmptyState {
                visible: Backend.isGeneric
                Layout.fillWidth: true
                title: qsTr("Easy-Switch needs a Logitech mouse")
                body: qsTr("This mouse is running in generic mode, which has no computer slots.")
            }
            Item { Layout.fillHeight: true; Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }
}
