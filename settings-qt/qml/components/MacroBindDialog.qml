import QtQuick
import QtQuick.Controls.Basic as B

// Bind a macro to a mouse button by pressing it (or picking it). Shows what
// the choice changes: another macro on that button is unbound, and a button
// remapped on the Buttons tab runs its remap instead unless it is reset.
// Open with bindFor(macroId, macroName, currentTrigger).
B.Popup {
    id: dlg
    property string macroId: ""
    property string macroName: ""
    property string trigger: ""        // chosen "mouse:N", "" = none
    property string _slot: ""          // named button slot of the trigger
    property bool _resetRemap: true
    property var _macros: []

    modal: true; dim: true; focus: true
    width: 480
    height: Math.min(implicitHeight, parent ? parent.height - 60 : 520)
    anchors.centerIn: B.Overlay.overlay
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside
    padding: 22

    readonly property var _slotTrigger: ({ back: "mouse:8", forward: "mouse:9", middle: "mouse:2" })
    readonly property var _slotDefault: ({ back: "back", forward: "forward", middle: "middle_click" })
    function _slotOf(t) {
        for (var s in _slotTrigger) if (_slotTrigger[s] === t) return s
        return ""
    }
    function _choose(t) { trigger = t; _slot = _slotOf(t) }

    function bindFor(mid, name, current) {
        macroId = mid; macroName = name
        _macros = Backend.listMacros()
        _choose(current || "")
        _resetRemap = true
        open()
    }

    readonly property var _other: {
        if (trigger === "") return null
        for (var i = 0; i < _macros.length; i++)
            if (_macros[i].id !== macroId && _macros[i].assigned_trigger === trigger) return _macros[i]
        return null
    }
    readonly property bool _remapped: _slot !== ""
        && Backend.buttonAction("", _slot, _slotDefault[_slot]) !== _slotDefault[_slot]

    function _apply() {
        if (_remapped && _resetRemap) Backend.restoreButton("", _slot)
        Backend.setMacroTrigger(macroId, trigger)
        close()
    }

    Connections {
        target: Backend
        enabled: dlg.opened
        function onButtonPressed(slot) {
            if (dlg._slotTrigger[slot]) dlg._choose(dlg._slotTrigger[slot])
        }
    }

    background: Rectangle {
        radius: Theme.radiusCard; color: Theme.surfaceGlassHi
        border.color: Theme.borderStrong; border.width: 1
    }
    B.Overlay.modal: Rectangle { color: "#99000000" }

    contentItem: Column {
        spacing: 16
        Column {
            width: parent.width; spacing: 4
            Text {
                text: qsTr("Bind “%1” to a button").arg(dlg.macroName)
                width: parent.width; elide: Text.ElideRight
                color: Theme.textPrimary; font.family: Theme.fontUI
                font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: qsTr("Press the button on your mouse, or pick it below.")
                color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            }
        }

        // Press here: native Back/Forward/wheel clicks reach the window; a
        // button the daemon already diverts arrives as ButtonPressed.
        Rectangle {
            width: parent.width; height: 84
            radius: Theme.radiusCtl
            color: pressMa.containsMouse ? Theme.accentSubtle : Theme.surfaceInset
            border.width: 1; border.color: dlg.trigger !== "" ? Theme.accent : Theme.border
            Column {
                anchors.centerIn: parent; spacing: 4
                ActionIcon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    iconName: "input-mouse-symbolic"; tint: Theme.accent; px: 24
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: dlg.trigger === "" ? qsTr("Waiting for a button…")
                          : Backend.macroTriggerOptions().filter(function (o) { return o.value === dlg.trigger })
                                .map(function (o) { return o.name })[0] || dlg.trigger
                    color: dlg.trigger === "" ? Theme.textMuted : Theme.textPrimary
                    font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
                }
            }
            MouseArea {
                id: pressMa
                anchors.fill: parent; hoverEnabled: true
                acceptedButtons: Qt.BackButton | Qt.ForwardButton | Qt.MiddleButton
                onPressed: (m) => {
                    if (m.button === Qt.BackButton) dlg._choose("mouse:8")
                    else if (m.button === Qt.ForwardButton) dlg._choose("mouse:9")
                    else if (m.button === Qt.MiddleButton) dlg._choose("mouse:2")
                }
            }
        }

        ComboBox {
            width: parent.width
            accessibleName: qsTr("Button")
            model: Backend.macroTriggerOptions().map(function (o) { return { id: o.value, name: o.name } })
            currentId: dlg.trigger
            onActivated2: (id) => dlg._choose(id)
        }

        // what the choice changes
        Text {
            visible: dlg._other !== null
            width: parent.width; wrapMode: Text.WordWrap
            text: dlg._other ? qsTr("“%1” uses this button now and will be unbound: one button runs one macro.")
                                   .arg(dlg._other.name || dlg._other.id) : ""
            color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
        }
        Row {
            visible: dlg._remapped
            width: parent.width; spacing: Theme.gapS
            Toggle {
                id: resetT
                anchors.verticalCenter: parent.verticalCenter
                checked: dlg._resetRemap
                accessibleName: qsTr("Reset the remap")
                onToggled: (v) => dlg._resetRemap = v
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - resetT.width - Theme.gapS; wrapMode: Text.WordWrap
                text: qsTr("This button is remapped on the Buttons tab, and a remap wins over a macro. Reset it so the macro runs.")
                color: Theme.textBody; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            }
        }

        Row {
            anchors.right: parent.right
            spacing: Theme.gapS
            PrimaryButton { text: qsTr("Cancel"); ghost: true; onClicked: dlg.close() }
            PrimaryButton {
                text: dlg.trigger === "" ? qsTr("Unbind") : qsTr("Bind")
                onClicked: dlg._apply()
            }
        }
    }
}
