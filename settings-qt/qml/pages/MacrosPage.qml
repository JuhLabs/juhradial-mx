import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as B
import "../components"

// Record and replay key/mouse sequences. Recording is wired to the daemon:
// the header button toggles capture, names + saves via Backend.stopMacroRecording.
Item {
    id: root
    anchors.fill: parent

    property var macros: []
    readonly property bool hasMacros: macros && macros.length > 0

    // Trigger options mapped to the ComboBox {id,name} shape; constant, built once.
    property var triggerModel: []
    function buildTriggers() {
        var opts = Backend.macroTriggerOptions(), out = []
        for (var i = 0; i < opts.length; i++)
            out.push({ id: opts[i].value, name: opts[i].name })
        return out
    }

    function refresh() { macros = Backend.listMacros() }
    Component.onCompleted: { triggerModel = buildTriggers(); refresh() }
    Connections {
        target: Backend
        function onMacrosChanged() { root.refresh() }
    }

    function toggleRecording() {
        if (Backend.recording) {
            var nm = nameField.text.length > 0 ? nameField.text : "New macro"
            if (Backend.stopMacroRecording(nm))
                nameField.text = ""
        } else {
            Backend.startMacroRecording()
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

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredHeight: root.hasMacros
                    ? headerCol.implicitHeight + Theme.gap + listCol.implicitHeight + Theme.padCard * 2
                    : headerCol.implicitHeight + 320 + Theme.padCard * 2

                Item {
                    anchors.fill: parent
                    anchors.margins: Theme.padCard

                    // ---- Header + recording controls + name field ----
                    Column {
                        id: headerCol
                        anchors.top: parent.top
                        anchors.left: parent.left
                        anchors.right: parent.right
                        spacing: Theme.gapS

                        CardHeader {
                            width: parent.width
                            title: "Macros"
                            subtitle: "Record and replay key and mouse sequences"
                            icon: "image://icon/" + Theme.accent.toString().slice(1) + "/" + Theme.iconStyle + "/applications-development-symbolic"

                            // trailing: live recording indicator + record/stop toggle
                            Row {
                                spacing: Theme.gapS
                                Item {
                                    width: indRow.width; height: 38
                                    visible: Backend.recording
                                    Row {
                                        id: indRow
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 6
                                        Rectangle {
                                            width: 9; height: 9; radius: 5
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: Theme.danger
                                            SequentialAnimation on opacity {
                                                running: root.visible && Backend.recording
                                                loops: Animation.Infinite
                                                NumberAnimation { from: 1.0; to: 0.2; duration: Theme.dLong; easing.type: Easing.InOutSine }
                                                NumberAnimation { from: 0.2; to: 1.0; duration: Theme.dLong; easing.type: Easing.InOutSine }
                                            }
                                        }
                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: "Recording…"
                                            color: Theme.danger
                                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
                                        }
                                    }
                                }
                                PrimaryButton {
                                    text: Backend.recording ? "Stop & save" : "Record"
                                    danger: Backend.recording
                                    onClicked: root.toggleRecording()
                                }
                            }
                        }

                        Rectangle { width: parent.width; height: 1; color: Theme.border }

                        SettingRow {
                            label: "Macro name"
                            desc: "Used when you save the next recording"
                            InputField {
                                id: nameField
                                width: 240
                                placeholder: "New macro"
                                onAccepted: if (!Backend.recording) Backend.startMacroRecording()
                            }
                        }

                        // Why a binding may never fire (only shown once macros exist)
                        Text {
                            visible: root.hasMacros
                            width: parent.width
                            text: "A trigger only fires from a button the daemon diverts (back, forward, side)."
                            color: Theme.textMuted
                            wrapMode: Text.WordWrap
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                        }
                    }

                    // ---- Body: empty state / capture hint / macro list ----
                    Item {
                        anchors.top: headerCol.bottom
                        anchors.topMargin: Theme.gap
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom

                        // Empty state (no macros, not recording)
                        EmptyState {
                            visible: !root.hasMacros && !Backend.recording
                            anchors.fill: parent
                            spot: "spot_macros"
                            title: "No macros yet"
                            body: "Record a key or mouse sequence once, then bind it to a button or a ring slice."
                            PrimaryButton {
                                text: "Start recording"; ghost: true
                                onClicked: Backend.startMacroRecording()
                            }
                        }

                        // Capture hint (recording with nothing saved yet)
                        Column {
                            visible: Backend.recording && !root.hasMacros
                            anchors.centerIn: parent
                            spacing: Theme.gapS
                            Rectangle {
                                width: 64; height: 64; radius: 32
                                anchors.horizontalCenter: parent.horizontalCenter
                                color: Theme.dangerSubtle
                                border.width: 1; border.color: Theme.danger
                                Rectangle {
                                    width: 16; height: 16; radius: 8
                                    anchors.centerIn: parent
                                    color: Theme.danger
                                    SequentialAnimation on scale {
                                        running: root.visible && Backend.recording
                                        loops: Animation.Infinite
                                        NumberAnimation { from: 0.7; to: 1.0; duration: Theme.dLong; easing.type: Easing.InOutSine }
                                        NumberAnimation { from: 1.0; to: 0.7; duration: Theme.dLong; easing.type: Easing.InOutSine }
                                    }
                                }
                            }
                            Text {
                                text: "Listening for input…"
                                color: Theme.textBody
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
                                anchors.horizontalCenter: parent.horizontalCenter
                            }
                            Text {
                                text: "Perform your sequence, then press Stop & save"
                                color: Theme.textMuted
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                anchors.horizontalCenter: parent.horizontalCenter
                            }
                        }

                        // Macro list
                        Column {
                            id: listCol
                            visible: root.hasMacros
                            anchors.top: parent.top
                            anchors.left: parent.left
                            anchors.right: parent.right
                            spacing: Theme.gapS

                            Repeater {
                                model: root.macros
                                Rectangle {
                                    required property var modelData
                                    width: listCol.width
                                    height: 58
                                    radius: Theme.radiusCtl
                                    color: rowHover.hovered ? "#16FFFFFF" : "#10FFFFFF"
                                    border.width: 1
                                    border.color: Theme.border
                                    Behavior on color { ColorAnimation { duration: Theme.dShort } }
                                    HoverHandler { id: rowHover }

                                    // Trigger picker + run / stop / delete (right side)
                                    Row {
                                        id: rowCtl
                                        anchors.right: parent.right
                                        anchors.rightMargin: 8
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: Theme.gapS
                                        ComboBox {
                                            anchors.verticalCenter: parent.verticalCenter
                                            width: 170
                                            model: root.triggerModel
                                            currentId: modelData.assigned_trigger ? modelData.assigned_trigger : ""
                                            onActivated2: (id) => {
                                                if (modelData.id !== undefined && modelData.id !== null)
                                                    Backend.setMacroTrigger(String(modelData.id), id)
                                            }
                                        }
                                        IconButton {
                                            anchors.verticalCenter: parent.verticalCenter
                                            icon: "document-edit-symbolic"
                                            tint: Theme.textBody
                                            onClicked: {
                                                if (modelData.id !== undefined && modelData.id !== null)
                                                    macroEditor.edit(String(modelData.id))
                                            }
                                        }
                                        IconButton {
                                            anchors.verticalCenter: parent.verticalCenter
                                            icon: "media-playback-start-symbolic"
                                            tint: Theme.accent
                                            onClicked: {
                                                if (modelData.id !== undefined && modelData.id !== null)
                                                    Backend.runMacro(String(modelData.id))
                                            }
                                        }
                                        IconButton {
                                            anchors.verticalCenter: parent.verticalCenter
                                            icon: "media-playback-stop-symbolic"
                                            tint: Theme.textBody
                                            onClicked: Backend.stopMacro()
                                        }
                                        IconButton {
                                            anchors.verticalCenter: parent.verticalCenter
                                            icon: "user-trash-symbolic"
                                            tint: Theme.textMuted
                                            onClicked: {
                                                if (modelData.id !== undefined && modelData.id !== null) {
                                                    Backend.deleteMacro(String(modelData.id))
                                                    Backend.notify("Macro deleted", "info")
                                                }
                                            }
                                        }
                                    }

                                    // Editable macro name
                                    Row {
                                        anchors.left: parent.left
                                        anchors.leftMargin: 12
                                        anchors.right: rowCtl.left
                                        anchors.rightMargin: Theme.gapS
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: Theme.gapS
                                        ActionIcon {
                                            anchors.verticalCenter: parent.verticalCenter
                                            iconName: "macros"; tint: Theme.accent; px: 18
                                        }
                                        InputField {
                                            id: nameEdit
                                            width: Math.min(280, parent.width - 30)
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: modelData.name ? modelData.name : ""
                                            placeholder: "Untitled macro"
                                            onEditingFinished: {
                                                if (modelData.id !== undefined && modelData.id !== null
                                                        && text !== (modelData.name || ""))
                                                    Backend.setMacroMeta(String(modelData.id), "name", text)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Item { Layout.fillWidth: true; Layout.preferredHeight: 4 }
        }
    }

    MacroEditor { id: macroEditor }
}
