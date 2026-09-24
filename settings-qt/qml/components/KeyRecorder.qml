import QtQuick
import "keys.js" as KeyNames

// Record a key chord: click the field and press the keys ("Ctrl + Shift + T").
// Modifier chips and a key list cover what a keyboard lacks (F13-F24) or the
// desktop grabs first (Print). `value` is the daemon's spelling
// ("ctrl+shift+t"); edited(value) fires on every change.
Column {
    id: rec
    property string value: ""
    signal edited(string value)
    spacing: Theme.gapS
    width: 360

    property bool recording: false
    property var _live: []          // modifiers held right now while recording
    readonly property var _parts: KeyNames.split(value)

    function _set(v) {
        if (v === value) return
        value = v
        edited(v)
    }
    function _toggleMod(m) {
        var mods = _parts.mods.slice()
        var i = mods.indexOf(m)
        if (i >= 0) mods.splice(i, 1); else mods.push(m)
        if (_parts.key !== "") _set(KeyNames.join(mods, _parts.key))
        else _pendingMods = mods
    }
    property var _pendingMods: []

    Rectangle {
        id: box
        width: parent.width; height: 44
        radius: Theme.radiusCtl
        color: rec.recording ? Theme.accentSubtle : (hov.hovered ? "#16FFFFFF" : "#12FFFFFF")
        border.width: 1
        border.color: rec.recording ? Theme.accent : (hov.hovered ? Theme.borderStrong : Theme.border)
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
        HoverHandler { id: hov; cursorShape: Qt.PointingHandCursor }
        FocusHalo { active: box.activeFocus; radius: Theme.radiusCtl }

        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: qsTr("Shortcut")
        Accessible.description: rec.value !== "" ? KeyNames.pretty(rec.value) : qsTr("Not set")
        Accessible.onPressAction: rec.startRecording()

        Text {
            anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
            verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
            text: rec.recording
                  ? (rec._live.length ? KeyNames.pretty(rec._live.join("+")) + " + …" : qsTr("Press the keys now, Esc to stop"))
                  : (rec.value !== "" ? KeyNames.pretty(rec.value) : qsTr("Click, then press the shortcut"))
            color: rec.recording || rec.value === "" ? Theme.textMuted : Theme.textPrimary
            font.family: rec.value !== "" && !rec.recording ? Theme.fontMono : Theme.fontUI
            font.pixelSize: rec.value !== "" && !rec.recording ? Theme.fsBody : Theme.fsSmall
            font.weight: Font.Medium
        }
        MouseArea { anchors.fill: parent; onClicked: rec.startRecording() }

        onActiveFocusChanged: if (!activeFocus) { rec.recording = false; rec._live = [] }
        Keys.onPressed: (e) => {
            if (!rec.recording) {
                if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Space) {
                    rec.startRecording(); e.accepted = true
                }
                return
            }
            e.accepted = true
            var mods = KeyNames.modsOf(e.modifiers)
            if (KeyNames.isModifierKey(e.key)) { rec._live = mods; return }
            if (e.key === Qt.Key_Escape && mods.length === 0) { rec.recording = false; return }
            var name = KeyNames.keyName(e.key, e.nativeScanCode)
            if (name === "") return
            rec._set(KeyNames.join(mods, name))
            rec.recording = false
            rec._live = []
        }
        Keys.onReleased: (e) => { if (rec.recording) rec._live = KeyNames.modsOf(e.modifiers) }
    }
    function startRecording() {
        box.forceActiveFocus()
        recording = true
        _live = []
    }

    // Modifier chips + a key the keyboard may not have.
    Row {
        spacing: 6
        Repeater {
            model: KeyNames.MODS
            Rectangle {
                required property string modelData
                readonly property bool on: rec._parts.key !== ""
                                           ? rec._parts.mods.indexOf(modelData) >= 0
                                           : rec._pendingMods.indexOf(modelData) >= 0
                width: chipTxt.implicitWidth + 20; height: 30; radius: 15
                color: on ? Theme.accentSubtle : "#0CFFFFFF"
                border.width: 1; border.color: on ? Theme.accent : Theme.border
                activeFocusOnTab: true
                Accessible.role: Accessible.CheckBox
                Accessible.name: KeyNames.prettyKey(modelData)
                Accessible.checkable: true
                Accessible.checked: on
                Accessible.onPressAction: rec._toggleMod(modelData)
                Keys.onSpacePressed: rec._toggleMod(modelData)
                FocusHalo { active: parent.activeFocus; radius: 15 }
                Text {
                    id: chipTxt; anchors.centerIn: parent
                    text: KeyNames.prettyKey(modelData)
                    color: parent.on ? Theme.accent : Theme.textBody
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall; font.weight: Font.Medium
                }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: rec._toggleMod(parent.modelData) }
            }
        }
        ComboBox {
            width: 150; height: 30
            accessibleName: qsTr("Special key")
            model: [{ id: "", name: qsTr("Other key…") }].concat(
                       KeyNames.EXTRA_KEYS.map(function (k) { return { id: k, name: KeyNames.prettyKey(k) } }))
            currentId: KeyNames.EXTRA_KEYS.indexOf(rec._parts.key) >= 0 ? rec._parts.key : ""
            onActivated2: (id) => {
                if (id === "") return
                var mods = rec._parts.key !== "" ? rec._parts.mods : rec._pendingMods
                rec._set(KeyNames.join(mods, id))
            }
        }
    }
}
