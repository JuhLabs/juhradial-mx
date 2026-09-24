import QtQuick

// One DPI control for every page that sets a DPI: the sensor's own range and
// step (Backend.dpiRange), a slider with step-sized keys, an editable mono
// field, and optional preset stops shown as ticks on the track and as chips
// below it.
//   value            the DPI to show; bind it, the control follows it
//   presets          DPI stops to show ([] = none)
//   presetsEditable  offer "Save as preset" and removing a stop
//   committed(int)   a new DPI, already snapped to what the sensor accepts
//   presetsEdited(list)
Item {
    id: dc
    property int value: 1000
    property var presets: []
    property bool presetsEditable: false
    property string accessibleName: qsTr("DPI")
    readonly property var range: Backend.dpiRange
    readonly property int shown: Math.round(sl.shown)
    readonly property int maxPresets: 6
    signal committed(int v)
    signal presetsEdited(var list)

    implicitWidth: 420
    implicitHeight: col.implicitHeight

    function commit(v) {
        var s = Backend.snapDpi(Math.round(v))
        dpiField.error = ""
        dc.committed(s)
    }
    function savePreset() {
        var list = dc.presets.slice()
        if (list.indexOf(dc.shown) < 0) list.push(dc.shown)
        list.sort(function (a, b) { return a - b })
        dc.presetsEdited(list)
    }
    function removePreset(v) {
        dc.presetsEdited(dc.presets.filter(function (p) { return p !== v }))
    }

    Column {
        id: col
        width: parent.width
        spacing: 12

        Row {
            width: parent.width
            spacing: 12
            Slider {
                id: sl
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - fieldRow.width - 12
                from: dc.range.min; to: dc.range.max
                stepSize: dc.range.step > 0 ? dc.range.step : 50
                pageStep: 500
                value: dc.value
                accessibleName: dc.accessibleName
                accessibleDescription: qsTr("%1 to %2 DPI").arg(dc.range.min).arg(dc.range.max)
                onCommitted: (v) => dc.commit(v)
                // the preset stops, under the track at their own positions
                Repeater {
                    model: dc.presets
                    Rectangle {
                        required property int modelData
                        width: 2; height: 7; radius: 1
                        color: Math.abs(dc.shown - modelData) < 1 ? Theme.accent : Theme.textMuted
                        x: 9 + (sl.width - 18) * (modelData - sl.from) / Math.max(1, sl.to - sl.from) - 1
                        y: sl.height / 2 + 6
                    }
                }
            }
            Row {
                id: fieldRow
                spacing: 6
                anchors.verticalCenter: parent.verticalCenter
                InputField {
                    id: dpiField
                    width: 76
                    mono: true
                    accessibleName: dc.accessibleName
                    accessibleDescription: qsTr("Type a DPI, then press Enter")
                    field.horizontalAlignment: TextInput.AlignRight
                    field.inputMethodHints: Qt.ImhDigitsOnly
                    field.validator: IntValidator { bottom: 0; top: 65535 }
                    onAccepted: {
                        var v = parseInt(dpiField.text, 10)
                        if (isNaN(v) || v < dc.range.min || v > dc.range.max) {
                            dpiField.error = qsTr("%1 to %2").arg(dc.range.min).arg(dc.range.max)
                            return
                        }
                        dc.commit(v)
                        dpiField.field.focus = false
                    }
                    onEditingFinished: if (dpiField.error === "") dpiField.text = String(dc.shown)
                }
                Binding {
                    target: dpiField; property: "text"
                    value: String(dc.shown)
                    when: !dpiField.field.activeFocus
                    restoreMode: Binding.RestoreNone
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: dpiField.error !== "" ? -10 : 0
                    text: qsTr("DPI")
                    color: Theme.textMuted
                    font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                }
            }
        }

        Flow {
            visible: dc.presets.length > 0 || dc.presetsEditable
            width: parent.width
            spacing: 6
            Repeater {
                model: dc.presets
                Rectangle {
                    id: chip
                    required property int modelData
                    readonly property bool active: Math.abs(dc.shown - modelData) < 1
                    readonly property bool canRemove: dc.presetsEditable && dc.presets.length > 1
                    width: chipTxt.implicitWidth + 24 + (canRemove && (chipHov.hovered || chip.activeFocus) ? 18 : 0)
                    height: 30; radius: 8
                    color: active ? Theme.accentSubtle : (chipHov.hovered ? "#1CFFFFFF" : "#12FFFFFF")
                    border.color: active ? Theme.accent : Theme.border; border.width: 1
                    Behavior on width { NumberAnimation { duration: Theme.dShort } }
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: qsTr("Set %1 DPI").arg(modelData)
                    Accessible.onPressAction: dc.commit(modelData)
                    Keys.onSpacePressed: dc.commit(modelData)
                    Keys.onReturnPressed: dc.commit(modelData)
                    Keys.onDeletePressed: if (canRemove) dc.removePreset(modelData)
                    FocusHalo { active: chip.activeFocus; radius: 8 }
                    HoverHandler { id: chipHov; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: dc.commit(chip.modelData) }
                    Text {
                        id: chipTxt
                        anchors.left: parent.left; anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: chip.modelData
                        color: chip.active ? Theme.accent : Theme.textBody
                        font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                    }
                    Text {
                        visible: chip.canRemove && (chipHov.hovered || chip.activeFocus)
                        anchors.right: parent.right; anchors.rightMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        text: "×"
                        color: rmHov.hovered ? Theme.danger : Theme.textMuted
                        font.pixelSize: Theme.fsBody
                        HoverHandler { id: rmHov }
                        TapHandler { onTapped: dc.removePreset(chip.modelData) }
                    }
                }
            }
            Rectangle {
                visible: dc.presetsEditable && dc.presets.indexOf(dc.shown) < 0 && dc.presets.length < dc.maxPresets
                width: addTxt.implicitWidth + 24; height: 30; radius: 8
                color: addHov.hovered ? "#1CFFFFFF" : "transparent"
                border.color: Theme.border; border.width: 1
                activeFocusOnTab: visible
                Accessible.role: Accessible.Button
                Accessible.name: addTxt.text
                Accessible.onPressAction: dc.savePreset()
                Keys.onSpacePressed: dc.savePreset()
                Keys.onReturnPressed: dc.savePreset()
                FocusHalo { active: parent.activeFocus; radius: 8 }
                HoverHandler { id: addHov; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: dc.savePreset() }
                Text {
                    id: addTxt
                    anchors.centerIn: parent
                    text: qsTr("+ Save %1 as a stop").arg(dc.shown)
                    color: Theme.textBody
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
                }
            }
        }
    }
}
