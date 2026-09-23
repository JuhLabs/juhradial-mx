import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as B

// Edit a stored macro's steps + replay behaviour. Open with open(macroId).
// Steps are the daemon's flat MacroAction list ({type:"delay",ms:50}, ...);
// delays and text are editable inline, every step can be reordered or removed,
// and you can append a delay/text step. Repeat mode + count and Duplicate live
// in the footer. Save writes back via Backend.saveMacroSteps + setMacroRepeat.
B.Popup {
    id: editor
    modal: true
    anchors.centerIn: parent
    width: 520
    height: Math.min(640, parent ? parent.height - 60 : 640)
    padding: 0

    property string macroId: ""
    property string macroName: ""
    property string repeatMode: "once"
    property int repeatCount: 3

    // Populate from a stored macro and show. (Named edit() so it does not
    // shadow Popup.open(), which it calls to drive the modal machinery.)
    function edit(mid) {
        var m = Backend.getMacro(mid)
        if (!m || m.id === undefined) return
        editor.macroId = String(m.id)
        editor.macroName = m.name ? m.name : "Macro"
        editor.repeatMode = m.repeat_mode ? m.repeat_mode : "once"
        editor.repeatCount = m.repeat_count ? m.repeat_count : 3
        stepModel.clear()
        var acts = m.actions ? m.actions : []
        for (var i = 0; i < acts.length; i++) {
            var a = acts[i]
            stepModel.append({
                stype: a.type ? a.type : "delay",
                key: a.key !== undefined ? String(a.key) : "",
                button: a.button !== undefined ? String(a.button) : "",
                text: a.text !== undefined ? String(a.text) : "",
                direction: a.direction !== undefined ? String(a.direction) : "",
                amount: a.amount !== undefined ? a.amount : 0,
                ms: a.ms !== undefined ? a.ms : 0
            })
        }
        open()
    }

    // Human label for a step row (the editable kinds get a field instead).
    function stepLabel(s) {
        switch (s.stype) {
        case "key_down": return "Key press  " + s.key
        case "key_up": return "Key release  " + s.key
        case "mouse_down": return "Mouse down  " + s.button
        case "mouse_up": return "Mouse up  " + s.button
        case "mouse_click": return "Mouse click  " + s.button
        case "scroll": return "Scroll " + s.direction + "  ×" + s.amount
        case "text": return "Type text"
        case "delay": return "Delay"
        default: return s.stype
        }
    }

    // Serialise the model back to the daemon's flat MacroAction list.
    function collectSteps() {
        var out = []
        for (var i = 0; i < stepModel.count; i++) {
            var s = stepModel.get(i)
            var o = { type: s.stype }
            if (s.stype === "delay") o.ms = Math.max(0, Math.round(s.ms))
            else if (s.stype === "text") o.text = s.text
            else if (s.stype === "key_down" || s.stype === "key_up") o.key = s.key
            else if (s.stype.indexOf("mouse") === 0) o.button = s.button
            else if (s.stype === "scroll") { o.direction = s.direction; o.amount = s.amount }
            out.push(o)
        }
        return out
    }

    function save() {
        Backend.saveMacroSteps(editor.macroId, collectSteps())
        Backend.setMacroRepeat(editor.macroId, editor.repeatMode, editor.repeatCount)
        editor.close()
    }

    ListModel { id: stepModel }

    background: Rectangle {
        radius: Theme.radiusCard
        color: Theme.surfaceGlassHi
        border.color: Theme.borderStrong; border.width: 1
    }

    contentItem: ColumnLayout {
        spacing: 0

        // ---- header ----
        Item {
            Layout.fillWidth: true; Layout.preferredHeight: 56
            Text {
                anchors.left: parent.left; anchors.leftMargin: Theme.padCard
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("Edit %1").arg(editor.macroName)
                color: Theme.textPrimary
                font.family: Theme.fontDisplay; font.pixelSize: Theme.fsH2; font.weight: Font.DemiBold
                elide: Text.ElideRight; width: parent.width - 100
            }
            IconButton {
                anchors.right: parent.right; anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                icon: "window-close-symbolic"; tint: Theme.textMuted; diameter: 34
                onClicked: editor.close()
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        // ---- steps ----
        Flickable {
            Layout.fillWidth: true; Layout.fillHeight: true
            contentHeight: stepsCol.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: stepsCol
                width: parent.width
                padding: Theme.padCard
                spacing: Theme.gapS

                Text {
                    width: parent.width - Theme.padCard * 2
                    visible: stepModel.count === 0
                    text: qsTr("This macro has no steps yet. Add a delay or some text below, or re-record it.")
                    color: Theme.textMuted; wrapMode: Text.WordWrap
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                }

                Repeater {
                    model: stepModel
                    Rectangle {
                        required property int index
                        required property var model
                        width: stepsCol.width - Theme.padCard * 2
                        height: 46
                        radius: Theme.radiusCtl
                        color: "#10FFFFFF"
                        border.width: 1; border.color: Theme.border

                        Row {
                            anchors.left: parent.left; anchors.leftMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Theme.gapS
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: (index + 1) + "."
                                color: Theme.textMuted
                                font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: model.stype !== "delay" && model.stype !== "text"
                                text: editor.stepLabel(model)
                                color: Theme.textBody
                                font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                            }
                            // editable: delay ms
                            Row {
                                visible: model.stype === "delay"
                                spacing: 6
                                anchors.verticalCenter: parent.verticalCenter
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: qsTr("Delay"); color: Theme.textBody
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                                }
                                Rectangle {
                                    width: 86; height: 30; radius: Theme.radiusCtl
                                    color: "#14FFFFFF"; border.width: 1
                                    border.color: msField.activeFocus ? Theme.accent : Theme.border
                                    B.TextField {
                                        id: msField
                                        anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 4
                                        text: String(model.ms)
                                        inputMethodHints: Qt.ImhDigitsOnly
                                        color: Theme.textBody; font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                                        verticalAlignment: Text.AlignVCenter; background: Item {}
                                        onEditingFinished: stepModel.setProperty(index, "ms", parseInt(text) || 0)
                                    }
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: qsTr("ms"); color: Theme.textMuted
                                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                }
                            }
                            // editable: text
                            Rectangle {
                                visible: model.stype === "text"
                                anchors.verticalCenter: parent.verticalCenter
                                width: 250; height: 30; radius: Theme.radiusCtl
                                color: "#14FFFFFF"; border.width: 1
                                border.color: txtField.activeFocus ? Theme.accent : Theme.border
                                B.TextField {
                                    id: txtField
                                    anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 6
                                    text: model.text
                                    placeholderText: qsTr("text to type")
                                    placeholderTextColor: Theme.textMuted
                                    color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                                    verticalAlignment: Text.AlignVCenter; background: Item {}
                                    onEditingFinished: stepModel.setProperty(index, "text", text)
                                }
                            }
                        }

                        // reorder + delete
                        Row {
                            anchors.right: parent.right; anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2
                            IconButton {
                                icon: "go-up-symbolic"; tint: Theme.textMuted; diameter: 30
                                enabled: index > 0
                                opacity: enabled ? 1 : 0.3
                                onClicked: { if (index > 0) stepModel.move(index, index - 1, 1) }
                            }
                            IconButton {
                                icon: "go-down-symbolic"; tint: Theme.textMuted; diameter: 30
                                enabled: index < stepModel.count - 1
                                opacity: enabled ? 1 : 0.3
                                onClicked: { if (index < stepModel.count - 1) stepModel.move(index, index + 1, 1) }
                            }
                            IconButton {
                                icon: "user-trash-symbolic"; tint: Theme.danger; diameter: 30
                                onClicked: stepModel.remove(index)
                            }
                        }
                    }
                }

                // add-step row
                Row {
                    spacing: Theme.gapS
                    PrimaryButton {
                        text: qsTr("Add delay"); ghost: true
                        onClicked: stepModel.append({ stype: "delay", key: "", button: "",
                            text: "", direction: "", amount: 0, ms: 100 })
                    }
                    PrimaryButton {
                        text: qsTr("Add text"); ghost: true
                        onClicked: stepModel.append({ stype: "text", key: "", button: "",
                            text: "", direction: "", amount: 0, ms: 0 })
                    }
                }
            }
        }

        // ---- footer: repeat + actions ----
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        Item {
            Layout.fillWidth: true; Layout.preferredHeight: 64
            Row {
                anchors.left: parent.left; anchors.leftMargin: Theme.padCard
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.gapS
                ComboBox {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 150
                    model: Backend.macroRepeatModes()
                    currentId: editor.repeatMode
                    onActivated2: (id) => editor.repeatMode = id
                }
                Stepper {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: editor.repeatMode === "repeat_n"
                    from: 1; to: 999
                    value: editor.repeatCount
                    onCommitted: (v) => editor.repeatCount = v
                }
            }
            Row {
                anchors.right: parent.right; anchors.rightMargin: Theme.padCard
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.gapS
                PrimaryButton {
                    text: qsTr("Duplicate"); ghost: true
                    onClicked: { Backend.duplicateMacro(editor.macroId); editor.close() }
                }
                PrimaryButton {
                    text: qsTr("Save")
                    onClicked: editor.save()
                }
            }
        }
    }
}
