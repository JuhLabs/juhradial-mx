import QtQuick
import QtQuick.Controls.Basic as B

// Full editor for one radial slice: pick the base action, then customise its
// label, command/URL and colour, and nudge its position. Reads/writes through
// `model` (the shared Slices unless set: sliceAt / setAction / setLabel / setCommand /
// setColor / swap). Open by setting `row` then open().
B.Popup {
    id: ed
    property int row: -1
    // The slices being edited: the global ring, or one app's (Backend.appSlices).
    property var model: Slices
    property var d: ({})

    modal: true; dim: true; focus: true
    width: 460
    height: Math.min(620, parent ? parent.height - 60 : 620)
    anchors.centerIn: B.Overlay.overlay
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside

    function reload() { ed.d = ed.model.sliceAt(ed.row) }
    onAboutToShow: reload()

    readonly property bool needsCommand: ["exec", "url"].indexOf(d.type || "") >= 0
    // What a slice does, in plain words (the raw type is an implementation detail).
    function typeWords(t) {
        switch (t) {
        case "exec": return qsTr("Runs a command")
        case "shortcut": return qsTr("Presses a shortcut")
        case "url": return qsTr("Opens a link")
        case "submenu": return qsTr("Opens quick links")
        case "settings": return qsTr("Opens JuhRadial MX settings")
        case "emoji": return qsTr("Opens the emoji picker")
        case "plugin": return qsTr("Runs a plugin action")
        case "macro": return qsTr("Runs a macro")
        case "none": return qsTr("Does nothing")
        default: return t || ""
        }
    }

    background: Rectangle {
        radius: Theme.radiusCard; color: Theme.surfaceGlassHi
        border.color: Theme.borderStrong; border.width: 1
    }
    B.Overlay.modal: Rectangle { color: "#99000000" }

    contentItem: Column {
        spacing: 14

        Row {
            width: parent.width
            Text {
                text: qsTr("Edit action %1").arg(ed.row + 1)
                color: Theme.textPrimary; font.family: Theme.fontUI
                font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                width: parent.width - moveRow.width
            }
            Row {
                id: moveRow
                spacing: 6
                IconButton { icon: "go-previous-symbolic"; diameter: 30; tint: Theme.textBody
                    onClicked: { var t = (ed.row + 7) % 8; ed.model.swap(ed.row, t); ed.row = t; ed.reload() } }
                IconButton { icon: "go-next-symbolic"; diameter: 30; tint: Theme.textBody
                    onClicked: { var t = (ed.row + 1) % 8; ed.model.swap(ed.row, t); ed.row = t; ed.reload() } }
            }
        }

        // ---- current action + change ----
        Rectangle {
            width: parent.width; height: 58; radius: Theme.radiusCtl
            color: "#0CFFFFFF"; border.color: Theme.border; border.width: 1
            Row {
                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 12
                Item {
                    width: 38; height: 38; anchors.verticalCenter: parent.verticalCenter
                    // a picked application icon (absolute path) wins over the family button
                    property string btn: (ed.d.icon || "").startsWith("/") ? ""
                                         : (Theme.iconStyle, Theme.sliceButton(ed.d.actionId || ""))
                    Image {
                        anchors.fill: parent; visible: parent.btn !== ""
                        source: parent.btn; sourceSize.width: 96; sourceSize.height: 96
                        smooth: true; fillMode: Image.PreserveAspectFit
                    }
                    ActionIcon {
                        anchors.centerIn: parent; visible: parent.btn === ""
                        iconName: ed.d.icon || ""; tint: ed.d.hex || Theme.accent
                        px: (ed.d.icon || "").startsWith("/") ? 30 : 22
                    }
                }
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 38 - changeBtn.width - pickBtn.width - 32
                    Text { text: ed.d.label || qsTr("No label"); color: Theme.textBody; elide: Text.ElideRight
                        width: parent.width; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium }
                    Text { text: ed.typeWords(ed.d.type); color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro }
                }
                PrimaryButton {
                    id: changeBtn; text: qsTr("Change"); ghost: true
                    anchors.verticalCenter: parent.verticalCenter
                    // plugin actions are read when the picker opens, so new plugins show without a restart
                    onClicked: { actPicker.actions = Backend.sliceActions(); actPicker.open() }
                }
                // Any slice can launch an installed application (#117): its
                // command and real icon replace what the slice did before.
                PrimaryButton {
                    id: pickBtn; text: qsTr("Pick application"); ghost: true
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: appPicker.open()
                }
            }
        }

        // ---- label ----
        Column {
            width: parent.width; spacing: 5
            Text { text: qsTr("Label"); color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall }
            Rectangle {
                width: parent.width; height: 38; radius: Theme.radiusCtl; color: "#14FFFFFF"
                border.color: lf.activeFocus ? Theme.accent : Theme.border; border.width: 1
                B.TextField {
                    id: lf; anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
                    text: ed.d.label || ""; color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                    verticalAlignment: Text.AlignVCenter; background: Item {}
                    onEditingFinished: if (text !== ed.d.label) ed.model.setLabel(ed.row, text)
                }
            }
        }

        // ---- command / url ----
        Column {
            width: parent.width; spacing: 5; visible: ed.needsCommand
            Row {
                width: parent.width
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width
                    text: ed.d.type === "url" ? qsTr("Link") : qsTr("Command")
                    color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                }
            }
            Rectangle {
                width: parent.width; height: 38; radius: Theme.radiusCtl; color: "#14FFFFFF"
                border.color: cf.activeFocus ? Theme.accent : Theme.border; border.width: 1
                B.TextField {
                    id: cf; anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
                    text: ed.d.command || ""; color: Theme.textBody; font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                    verticalAlignment: Text.AlignVCenter; background: Item {}
                    onEditingFinished: if (text !== ed.d.command) ed.model.setCommand(ed.row, text)
                }
            }
        }

        // ---- shortcut: recorded, not typed (PgUp, F13 and friends) ----
        Column {
            width: parent.width; spacing: 5; visible: ed.d.type === "shortcut"
            Text { text: qsTr("Shortcut"); color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall }
            KeyRecorder {
                width: parent.width
                value: ed.d.type === "shortcut" ? (ed.d.command || "") : ""
                onEdited: (v) => { ed.model.setCommand(ed.row, v); ed.reload() }
            }
        }

        // ---- colour ----
        Column {
            width: parent.width; spacing: 6
            Text { text: qsTr("Colour"); color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall }
            Row {
                spacing: 8
                Repeater {
                    model: Backend.sliceColors()
                    Rectangle {
                        required property var modelData
                        width: 28; height: 28; radius: 14; color: modelData.hex
                        border.width: ed.d.color === modelData.name ? 3 : (cma.containsMouse ? 2 : 1)
                        border.color: ed.d.color === modelData.name || cma.containsMouse ? Theme.textPrimary : Theme.border
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.name
                        Accessible.checked: ed.d.color === modelData.name
                        MouseArea {
                            id: cma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { ed.model.setColor(ed.row, modelData.name); ed.reload() }
                        }
                    }
                }
            }
        }

        Row {
            width: parent.width
            Item { width: parent.width - doneBtn.width; height: 1 }
            PrimaryButton { id: doneBtn; text: qsTr("Done"); onClicked: ed.close() }
        }
    }

    ActionPicker {
        id: actPicker
        title: qsTr("Choose an action")
        actions: []
        currentId: ed.d.actionId || ""
        onPicked: (id) => { ed.model.setAction(ed.row, id); ed.reload() }
    }
    AppPicker {
        id: appPicker
        onPicked: (app) => {
            ed.model.setApp(ed.row, app.command, app.name, Backend.cacheAppIcon(app.id))
            ed.reload()
        }
    }
}
