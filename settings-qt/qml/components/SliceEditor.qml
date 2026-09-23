import QtQuick
import QtQuick.Controls.Basic as B

// Full editor for one radial slice: pick the base action, then customise its
// label, command/URL and colour, and nudge its position. Reads/writes through
// the shared Slices model (Slices.sliceAt / setAction / setLabel / setCommand /
// setColor / swap). Open by setting `row` then open().
B.Popup {
    id: ed
    property int row: -1
    property var d: ({})

    modal: true; dim: true; focus: true
    width: 460
    height: Math.min(620, parent ? parent.height - 60 : 620)
    anchors.centerIn: B.Overlay.overlay
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside

    function reload() { ed.d = Slices.sliceAt(ed.row) }
    onAboutToShow: reload()

    readonly property bool needsCommand: ["exec", "shortcut", "url"].indexOf(d.type || "") >= 0

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
                text: "Edit action " + (ed.row + 1)
                color: Theme.textPrimary; font.family: Theme.fontUI
                font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                width: parent.width - moveRow.width
            }
            Row {
                id: moveRow
                spacing: 6
                IconButton { icon: "go-previous-symbolic"; diameter: 30; tint: Theme.textBody
                    onClicked: { var t = (ed.row + 7) % 8; Slices.swap(ed.row, t); ed.row = t; ed.reload() } }
                IconButton { icon: "go-next-symbolic"; diameter: 30; tint: Theme.textBody
                    onClicked: { var t = (ed.row + 1) % 8; Slices.swap(ed.row, t); ed.row = t; ed.reload() } }
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
                    property string btn: (Theme.iconStyle, Theme.sliceButton(ed.d.actionId || ""))
                    Image {
                        anchors.fill: parent; visible: parent.btn !== ""
                        source: parent.btn; sourceSize.width: 96; sourceSize.height: 96
                        smooth: true; fillMode: Image.PreserveAspectFit
                    }
                    ActionIcon {
                        anchors.centerIn: parent; visible: ((Theme.iconStyle, Theme.sliceButton(ed.d.actionId || ""))) === ""
                        iconName: ed.d.icon || ""; tint: ed.d.hex || Theme.accent; px: 22
                    }
                }
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 38 - changeBtn.width - 24
                    Text { text: ed.d.label || "—"; color: Theme.textBody; elide: Text.ElideRight
                        width: parent.width; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.Medium }
                    Text { text: ed.d.type || ""; color: Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro }
                }
                PrimaryButton {
                    id: changeBtn; text: "Change"; ghost: true
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: actPicker.open()
                }
            }
        }

        // ---- label ----
        Column {
            width: parent.width; spacing: 5
            Text { text: "Label"; color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall }
            Rectangle {
                width: parent.width; height: 38; radius: Theme.radiusCtl; color: "#14FFFFFF"
                border.color: lf.activeFocus ? Theme.accent : Theme.border; border.width: 1
                B.TextField {
                    id: lf; anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
                    text: ed.d.label || ""; color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                    verticalAlignment: Text.AlignVCenter; background: Item {}
                    onEditingFinished: if (text !== ed.d.label) Slices.setLabel(ed.row, text)
                }
            }
        }

        // ---- command / url ----
        Column {
            width: parent.width; spacing: 5; visible: ed.needsCommand
            Text { text: (ed.d.type === "url" ? "URL" : (ed.d.type === "shortcut" ? "Shortcut (e.g. ctrl+c)" : "Command"))
                color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall }
            Rectangle {
                width: parent.width; height: 38; radius: Theme.radiusCtl; color: "#14FFFFFF"
                border.color: cf.activeFocus ? Theme.accent : Theme.border; border.width: 1
                B.TextField {
                    id: cf; anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
                    text: ed.d.command || ""; color: Theme.textBody; font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                    verticalAlignment: Text.AlignVCenter; background: Item {}
                    onEditingFinished: if (text !== ed.d.command) Slices.setCommand(ed.row, text)
                }
            }
        }

        // ---- colour ----
        Column {
            width: parent.width; spacing: 6
            Text { text: "Colour"; color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall }
            Row {
                spacing: 8
                Repeater {
                    model: Backend.sliceColors()
                    Rectangle {
                        required property var modelData
                        width: 28; height: 28; radius: 14; color: modelData.hex
                        border.width: ed.d.color === modelData.name ? 3 : 1
                        border.color: ed.d.color === modelData.name ? Theme.textPrimary : Theme.border
                        scale: cma.containsMouse || ed.d.color === modelData.name ? 1.12 : 1.0
                        Behavior on scale { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }
                        MouseArea {
                            id: cma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { Slices.setColor(ed.row, modelData.name); ed.reload() }
                        }
                    }
                }
            }
        }

        Row {
            width: parent.width
            Item { width: parent.width - doneBtn.width; height: 1 }
            PrimaryButton { id: doneBtn; text: "Done"; onClicked: ed.close() }
        }
    }

    ActionPicker {
        id: actPicker
        title: "Choose an action"
        actions: Backend.radialActions()
        currentId: ed.d.actionId || ""
        onPicked: (id) => { Slices.setAction(ed.row, id); ed.reload() }
    }
}
