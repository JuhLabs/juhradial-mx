import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as B
import "keys.js" as KeyNames

// Edit a stored macro. Steps show as keycaps (a key press and release, with
// the modifiers held around it, is one step), with pauses, typed text,
// clicks and scrolling. Drag the handle to reorder; new steps go after the
// selected one. Timing plays back as recorded or with a fixed gap; the
// repeat mode says what it does. Unsaved changes are never dropped by a
// stray click. Open with edit(macroId).
B.Popup {
    id: editor
    modal: true
    anchors.centerIn: parent
    width: 580
    height: Math.min(700, parent ? parent.height - 40 : 700)
    padding: 0
    closePolicy: dirty ? B.Popup.NoAutoClose : (B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside)

    property string macroId: ""
    property string macroName: ""
    property string trigger: ""
    property string repeatMode: "once"
    property int repeatCount: 3
    property bool fixedGap: false
    property int gap: 50
    property bool dirty: false
    property int selected: -1
    property bool confirmClose: false

    function edit(mid) {
        var m = Backend.getMacro(mid)
        if (!m || m.id === undefined) return
        macroId = String(m.id)
        macroName = m.name ? m.name : ""
        trigger = m.assigned_trigger || ""
        repeatMode = m.repeat_mode ? m.repeat_mode : "once"
        repeatCount = m.repeat_count ? m.repeat_count : 3
        fixedGap = m.use_standard_delay === undefined ? true : !!m.use_standard_delay
        gap = m.standard_delay_ms !== undefined ? m.standard_delay_ms : 50
        rows.clear()
        var r = Backend.macroEditorRows(macroId)
        for (var i = 0; i < r.length; i++) rows.append(_row(r[i]))
        selected = -1; dirty = false; confirmClose = false
        open()
    }
    // One ListModel shape for every kind (roles must not change per row).
    function _row(r) {
        return { kind: r.kind || "raw", chord: r.chord || "", hold: r.hold || 0, ms: r.ms || 0, text: r.text || "",
                 button: r.button || "left", direction: r.direction || "down",
                 amount: r.amount || 1, raw: r.action ? JSON.stringify(r.action) : "" }
    }
    function _collect() {
        var out = []
        for (var i = 0; i < rows.count; i++) {
            var r = rows.get(i)
            var o = { kind: r.kind, chord: r.chord, hold: r.hold, ms: r.ms, text: r.text,
                      button: r.button, direction: r.direction, amount: r.amount }
            if (r.kind === "raw" && r.raw !== "") o.action = JSON.parse(r.raw)
            out.push(o)
        }
        return out
    }
    function add(kind) {
        var r = _row({ kind: kind, chord: "", ms: 100, text: "", amount: 3 })
        var at = selected >= 0 ? selected + 1 : rows.count
        rows.insert(at, r)
        selected = at
        dirty = true
    }
    function set(i, role, v) { rows.setProperty(i, role, v); dirty = true }
    function save() {
        if (macroName.trim() !== "") Backend.setMacroMeta(macroId, "name", macroName.trim())
        Backend.saveMacroRows(macroId, _collect())
        Backend.setMacroTiming(macroId, fixedGap, gap)
        Backend.setMacroRepeat(macroId, repeatMode, repeatCount)
        dirty = false
    }
    function tryClose() {
        if (dirty) confirmClose = true
        else close()
    }
    function rowText(r) {
        switch (r.kind) {
        case "keys": return r.chord === "" ? qsTr("Record the keys") : KeyNames.pretty(r.chord)
        case "delay": return qsTr("Pause %1 ms").arg(r.ms)
        case "text": return r.text === "" ? qsTr("Type text") : qsTr("Type “%1”").arg(r.text)
        case "click": return qsTr("Click %1").arg(buttonName(r.button))
        case "scroll": return qsTr("Scroll %1 × %2").arg(directionName(r.direction)).arg(r.amount)
        default: return r.raw
        }
    }
    function buttonName(b) {
        return { left: qsTr("left"), right: qsTr("right"), middle: qsTr("middle"),
                 back: qsTr("back"), forward: qsTr("forward") }[b] || b
    }
    function directionName(d) {
        return { up: qsTr("up"), down: qsTr("down"), left: qsTr("left"), right: qsTr("right") }[d] || d
    }
    readonly property var modes: Backend.macroRepeatModes()
    readonly property var modeInfo: {
        for (var i = 0; i < modes.length; i++) if (modes[i].id === repeatMode) return modes[i]
        return { id: repeatMode, name: repeatMode, desc: "" }
    }
    readonly property bool needsTrigger: repeatMode === "while_holding" || repeatMode === "toggle"

    ListModel { id: rows }

    background: Rectangle {
        radius: Theme.radiusCard
        color: Theme.surfaceGlassHi
        border.color: Theme.borderStrong; border.width: 1
    }

    contentItem: ColumnLayout {
        spacing: 0

        // ---- header: the name ----
        RowLayout {
            Layout.fillWidth: true; Layout.preferredHeight: 64
            Layout.leftMargin: Theme.padCard; Layout.rightMargin: 10
            spacing: Theme.gapS
            InputField {
                Layout.fillWidth: true
                accessibleName: qsTr("Macro name")
                text: editor.macroName
                placeholder: qsTr("Macro name")
                onTextEdited: { editor.macroName = text; editor.dirty = true }
            }
            IconButton {
                icon: "window-close-symbolic"; tint: Theme.textMuted; diameter: 34
                tip: qsTr("Close")
                onClicked: editor.tryClose()
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        // ---- steps ----
        ListView {
            id: list
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.leftMargin: Theme.padCard; Layout.rightMargin: Theme.padCard
            Layout.topMargin: Theme.gapS
            clip: true
            spacing: 6
            model: rows
            boundsBehavior: Flickable.StopAtBounds
            B.ScrollBar.vertical: B.ScrollBar { policy: B.ScrollBar.AsNeeded }
            property int dragFrom: -1

            Text {
                width: list.width
                visible: rows.count === 0
                text: qsTr("No steps yet. Add keys, text, a pause, a click or scrolling below.")
                color: Theme.textMuted; wrapMode: Text.WordWrap
                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            }

            delegate: Rectangle {
                id: rowItem
                required property int index
                required property var model
                readonly property bool sel: editor.selected === index
                width: list.width
                height: sel ? rowCol.implicitHeight + 16 : 46
                radius: Theme.radiusCtl
                color: sel ? Theme.accentSubtle : (rowHov.hovered ? "#16FFFFFF" : "#10FFFFFF")
                border.width: 1; border.color: sel ? Theme.accent : Theme.border
                opacity: list.dragFrom === index ? 0.6 : 1
                HoverHandler { id: rowHov }
                activeFocusOnTab: true
                Accessible.role: Accessible.ListItem
                Accessible.name: qsTr("Step %1: %2").arg(index + 1).arg(editor.rowText(model))
                Keys.onReturnPressed: editor.selected = sel ? -1 : index
                Keys.onDeletePressed: { rows.remove(index); editor.dirty = true; editor.selected = -1 }
                FocusHalo { active: rowItem.activeFocus; radius: Theme.radiusCtl }

                MouseArea {
                    anchors.fill: parent
                    onClicked: editor.selected = rowItem.sel ? -1 : rowItem.index
                }

                Column {
                    id: rowCol
                    x: 8; y: 8
                    width: parent.width - 16
                    spacing: 8
                    RowLayout {
                        width: parent.width; height: 30
                        spacing: Theme.gapS
                        // drag handle
                        Text {
                            text: "⠿"; color: Theme.textMuted
                            font.pixelSize: 18
                            Accessible.ignored: true
                            MouseArea {
                                anchors.fill: parent; anchors.margins: -6
                                cursorShape: Qt.SizeVerCursor
                                preventStealing: true
                                onPressed: { editor.selected = -1; list.dragFrom = rowItem.index }
                                onPositionChanged: (m) => {
                                    if (list.dragFrom < 0) return
                                    var p = mapToItem(list.contentItem, m.x, m.y)
                                    var to = list.indexAt(10, p.y)
                                    if (to >= 0 && to !== list.dragFrom) {
                                        rows.move(list.dragFrom, to, 1)
                                        list.dragFrom = to
                                        editor.dirty = true
                                    }
                                }
                                onReleased: list.dragFrom = -1
                            }
                        }
                        Text {
                            text: (rowItem.index + 1) + "."
                            color: Theme.textMuted
                            font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
                        }
                        // keycaps for key steps, plain words for the rest
                        Row {
                            visible: model.kind === "keys" && model.chord !== ""
                            spacing: 4
                            Repeater {
                                model: rowItem.model.kind === "keys" ? rowItem.model.chord.split("+").filter(function (k) { return k !== "" }) : []
                                Rectangle {
                                    required property string modelData
                                    height: 24; width: capTxt.implicitWidth + 14; radius: 5
                                    color: Theme.surfaceInset; border.width: 1; border.color: Theme.borderStrong
                                    Text {
                                        id: capTxt; anchors.centerIn: parent
                                        text: KeyNames.prettyKey(modelData)
                                        color: Theme.textPrimary
                                        font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall; font.weight: Font.DemiBold
                                    }
                                }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: !(model.kind === "keys" && model.chord !== "")
                            text: editor.rowText(model)
                            elide: Text.ElideRight
                            color: Theme.textBody
                            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                        }
                        Item { Layout.fillWidth: true; visible: model.kind === "keys" && model.chord !== "" }
                        Text {
                            visible: model.kind === "keys" && model.hold > 0
                            text: qsTr("held %1 ms").arg(model.hold)
                            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
                        }
                        IconButton {
                            icon: "user-trash-symbolic"; tint: Theme.textMuted; diameter: 30
                            tip: qsTr("Remove this step")
                            onClicked: { rows.remove(rowItem.index); editor.dirty = true; editor.selected = -1 }
                        }
                    }

                    // ---- the selected step's editor ----
                    KeyRecorder {
                        visible: rowItem.sel && model.kind === "keys"
                        width: parent.width
                        value: model.kind === "keys" ? model.chord : ""
                        onEdited: (v) => editor.set(rowItem.index, "chord", v)
                    }
                    Row {
                        visible: rowItem.sel && model.kind === "delay"
                        spacing: Theme.gapS
                        Stepper {
                            from: 0; to: 60000; step: 50; suffix: " ms"
                            accessibleName: qsTr("Pause")
                            value: model.ms
                            onCommitted: (v) => editor.set(rowItem.index, "ms", v)
                        }
                    }
                    InputField {
                        visible: rowItem.sel && model.kind === "text"
                        width: parent.width
                        accessibleName: qsTr("Text to type")
                        placeholder: qsTr("Text to type")
                        text: model.kind === "text" ? model.text : ""
                        onTextEdited: editor.set(rowItem.index, "text", text)
                    }
                    ComboBox {
                        visible: rowItem.sel && rowItem.model.kind === "click"
                        width: 200
                        accessibleName: qsTr("Mouse button")
                        model: ["left", "right", "middle", "back", "forward"].map(function (b) { return { id: b, name: editor.buttonName(b) } })
                        currentId: rowItem.model.button
                        onActivated2: (id) => editor.set(rowItem.index, "button", id)
                    }
                    Row {
                        visible: rowItem.sel && model.kind === "scroll"
                        spacing: Theme.gapS
                        ComboBox {
                            width: 160
                            accessibleName: qsTr("Direction")
                            model: ["up", "down"].map(function (d) { return { id: d, name: editor.directionName(d) } })
                            currentId: rowItem.model.direction
                            onActivated2: (id) => editor.set(rowItem.index, "direction", id)
                        }
                        Stepper {
                            from: 1; to: 50
                            accessibleName: qsTr("Steps")
                            value: rowItem.model.amount
                            onCommitted: (v) => editor.set(rowItem.index, "amount", v)
                        }
                    }
                }
            }
        }

        // ---- add a step (after the selected one) ----
        Flow {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.padCard; Layout.rightMargin: Theme.padCard
            Layout.topMargin: Theme.gapS; Layout.bottomMargin: Theme.gapS
            spacing: Theme.gapS
            Text {
                height: 38; verticalAlignment: Text.AlignVCenter
                text: editor.selected >= 0 ? qsTr("Add after step %1").arg(editor.selected + 1) : qsTr("Add")
                color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            }
            PrimaryButton { text: qsTr("Keys"); ghost: true; onClicked: editor.add("keys") }
            PrimaryButton { text: qsTr("Text"); ghost: true; onClicked: editor.add("text") }
            PrimaryButton { text: qsTr("Pause"); ghost: true; onClicked: editor.add("delay") }
            PrimaryButton { text: qsTr("Click"); ghost: true; onClicked: editor.add("click") }
            PrimaryButton { text: qsTr("Scroll"); ghost: true; onClicked: editor.add("scroll") }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

        // ---- timing + repeat ----
        GridLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.padCard; Layout.rightMargin: Theme.padCard
            Layout.topMargin: Theme.gapS
            columns: 2; columnSpacing: Theme.gap; rowSpacing: Theme.gapS
            Text {
                text: qsTr("Timing"); color: Theme.textMuted
                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            }
            Row {
                spacing: Theme.gapS
                SegmentedControl {
                    width: 260
                    accessibleName: qsTr("Timing")
                    model: [{ id: "recorded", name: qsTr("As recorded") }, { id: "fixed", name: qsTr("Fixed gap") }]
                    currentId: editor.fixedGap ? "fixed" : "recorded"
                    onActivated: (id) => { editor.fixedGap = id === "fixed"; editor.dirty = true }
                }
                Stepper {
                    visible: editor.fixedGap
                    from: 0; to: 2000; step: 10; suffix: " ms"
                    accessibleName: qsTr("Gap between steps")
                    value: editor.gap
                    onCommitted: (v) => { editor.gap = v; editor.dirty = true }
                }
            }
            Text {
                text: qsTr("Repeat"); color: Theme.textMuted
                font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            }
            Row {
                spacing: Theme.gapS
                ComboBox {
                    width: 200
                    accessibleName: qsTr("Repeat")
                    // While held and On / off need a bound button.
                    model: editor.modes.filter(function (m) {
                        return editor.trigger !== "" || (m.id !== "while_holding" && m.id !== "toggle") || m.id === editor.repeatMode
                    })
                    currentId: editor.repeatMode
                    onActivated2: (id) => { editor.repeatMode = id; editor.dirty = true }
                }
                Stepper {
                    visible: editor.repeatMode === "repeat_n"
                    from: 1; to: 999; suffix: "×"
                    accessibleName: qsTr("Times")
                    value: editor.repeatCount
                    onCommitted: (v) => { editor.repeatCount = v; editor.dirty = true }
                }
            }
            Item { width: 1; height: 1 }
            Text {
                Layout.fillWidth: true; wrapMode: Text.WordWrap
                text: editor.modeInfo.desc
                      + (editor.needsTrigger && editor.trigger === "" ? " " + qsTr("Bind the macro to a button first.") : "")
                color: editor.needsTrigger && editor.trigger === "" ? Theme.danger : Theme.textMuted
                font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
            }
        }

        // ---- footer ----
        RowLayout {
            Layout.fillWidth: true; Layout.preferredHeight: 64
            Layout.leftMargin: Theme.padCard; Layout.rightMargin: Theme.padCard
            spacing: Theme.gapS
            // Leaving with unsaved changes asks first.
            Text {
                visible: editor.confirmClose
                Layout.fillWidth: true; wrapMode: Text.WordWrap
                text: qsTr("You have unsaved changes.")
                color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            }
            PrimaryButton {
                visible: editor.confirmClose
                text: qsTr("Discard"); ghost: true; danger: true
                onClicked: { editor.dirty = false; editor.close() }
            }
            PrimaryButton {
                visible: editor.confirmClose
                text: qsTr("Keep editing"); ghost: true
                onClicked: editor.confirmClose = false
            }
            PrimaryButton {
                visible: !editor.confirmClose
                text: qsTr("Test"); ghost: true
                onClicked: Backend.testMacro(editor.macroId, editor._collect(), editor.fixedGap, editor.gap)
            }
            PrimaryButton {
                visible: !editor.confirmClose
                text: qsTr("Duplicate"); ghost: true
                onClicked: {
                    if (editor.dirty) editor.save()
                    var copy = Backend.duplicateMacro(editor.macroId)
                    if (copy !== "") editor.edit(copy)
                }
            }
            Item { Layout.fillWidth: true; visible: !editor.confirmClose }
            PrimaryButton {
                visible: !editor.confirmClose
                text: qsTr("Save")
                onClicked: { editor.save(); editor.close() }
            }
        }
    }
}
