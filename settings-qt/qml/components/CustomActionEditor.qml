import QtQuick
import QtQuick.Controls.Basic as B

// What a button set to "Custom action" does: a recorded shortcut, an
// application, a command, a link, a saved macro or a plugin action. Saved as
// buttons.custom.<slot> (or the scope's own copy) through
// Backend.setCustomAction. Open with openFor(scope, slot, buttonName).
B.Popup {
    id: ed
    property string scope: ""
    property string slot: ""
    property string buttonName: ""
    signal saved

    property string kind: "shortcut"   // shortcut | app | command | url | macro | plugin
    property string value: ""
    property string label: ""
    property string icon: ""
    property var _macros: []
    property var _plugins: []

    modal: true; dim: true; focus: true
    width: 500
    height: Math.min(implicitHeight, parent ? parent.height - 60 : 560)
    anchors.centerIn: B.Overlay.overlay
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside
    padding: 22

    function openFor(scope, slot, name) {
        ed.scope = scope; ed.slot = slot; ed.buttonName = name
        var c = Backend.customAction(scope, slot)
        ed.value = c.value || ""; ed.label = c.label || ""; ed.icon = c.icon || ""
        // An application is a command with the app's name and icon.
        ed.kind = (c.kind === "command" && ed.icon !== "") ? "app" : (c.kind || "shortcut")
        ed._loadLists()
        open()
    }
    function _loadLists() {
        if (kind === "macro" && _macros.length === 0) _macros = Backend.listMacros()
        if (kind === "plugin" && _plugins.length === 0) _plugins = Backend.pluginActions()
    }
    onKindChanged: _loadLists()

    readonly property string _error: {
        var v = value.trim()
        if (v === "") return ""
        if (kind === "url" && !/^(https?:\/\/.+|mailto:.+)/i.test(v))
            return qsTr("A link starts with https://, http:// or mailto:")
        return ""
    }
    readonly property bool _ready: value.trim() !== "" && _error === ""

    function _save() {
        var ok = Backend.setCustomAction(scope, slot, {
            kind: kind === "app" ? "command" : kind,
            value: value.trim(),
            label: (kind === "app" || kind === "macro" || kind === "plugin") ? label : "",
            icon: kind === "app" ? icon : ""
        })
        if (ok) { saved(); close() }
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
                text: qsTr("Custom action")
                color: Theme.textPrimary; font.family: Theme.fontUI
                font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: qsTr("What %1 does when you press it").arg(ed.buttonName)
                color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
            }
        }

        SegmentedControl {
            width: parent.width
            accessibleName: qsTr("Kind of action")
            model: [{ id: "shortcut", name: qsTr("Shortcut") }, { id: "app", name: qsTr("App") },
                    { id: "command", name: qsTr("Command") }, { id: "url", name: qsTr("Link") },
                    { id: "macro", name: qsTr("Macro") }, { id: "plugin", name: qsTr("Plugin") }]
            currentId: ed.kind
            onActivated: (id) => {
                if (id === ed.kind) return
                ed.kind = id; ed.value = ""; ed.label = ""; ed.icon = ""
            }
        }

        // ---- shortcut ----
        KeyRecorder {
            visible: ed.kind === "shortcut"
            width: parent.width
            value: ed.kind === "shortcut" ? ed.value : ""
            onEdited: (v) => ed.value = v
        }

        // ---- application ----
        Row {
            visible: ed.kind === "app"
            width: parent.width; spacing: Theme.gap
            Rectangle {
                width: parent.width - pickApp.width - Theme.gap; height: 44
                radius: Theme.radiusCtl; color: "#12FFFFFF"
                border.width: 1; border.color: Theme.border
                Row {
                    anchors.fill: parent; anchors.leftMargin: 12; spacing: 10
                    ActionIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: ed.icon !== ""
                        iconName: ed.icon; tint: Theme.textBody; px: 24
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: ed.label !== "" ? ed.label : qsTr("No application chosen")
                        color: ed.label !== "" ? Theme.textPrimary : Theme.textMuted
                        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
                    }
                }
            }
            PrimaryButton {
                id: pickApp; ghost: true
                text: qsTr("Choose…")
                onClicked: appPicker.open()
            }
        }

        // ---- command / link ----
        InputField {
            visible: ed.kind === "command" || ed.kind === "url"
            width: parent.width
            mono: true
            accessibleName: ed.kind === "url" ? qsTr("Link") : qsTr("Command")
            placeholder: ed.kind === "url" ? "https://" : qsTr("for example: konsole -e htop")  // i18n-ignore
            text: (ed.kind === "command" || ed.kind === "url") ? ed.value : ""
            error: ed._error
            onTextEdited: ed.value = text
        }

        // ---- macro / plugin ----
        ComboBox {
            visible: ed.kind === "macro"
            width: parent.width
            accessibleName: qsTr("Macro")
            model: [{ id: "", name: ed._macros.length ? qsTr("Choose a macro") : qsTr("No saved macros yet") }]
                   .concat(ed._macros.map(function (m) { return { id: m.id, name: m.name || m.id } }))
            currentId: ed.kind === "macro" ? ed.value : ""
            onActivated2: (id) => {
                ed.value = id
                var m = ed._macros.filter(function (x) { return x.id === id })[0]
                ed.label = m ? (m.name || m.id) : ""
            }
        }
        ComboBox {
            visible: ed.kind === "plugin"
            width: parent.width
            accessibleName: qsTr("Plugin action")
            model: [{ id: "", name: ed._plugins.length ? qsTr("Choose a plugin action") : qsTr("No plugins installed") }]
                   .concat(ed._plugins.map(function (p) { return { id: p.command, name: p.name } }))
            currentId: ed.kind === "plugin" ? ed.value : ""
            onActivated2: (id) => {
                ed.value = id
                var p = ed._plugins.filter(function (x) { return x.command === id })[0]
                ed.label = p ? p.label : ""
            }
        }

        Text {
            width: parent.width; wrapMode: Text.WordWrap
            visible: ed.kind === "command"
            text: qsTr("Runs through the shell, like a terminal would.")
            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
        }

        Row {
            anchors.right: parent.right
            spacing: Theme.gapS
            PrimaryButton { text: qsTr("Cancel"); ghost: true; onClicked: ed.close() }
            PrimaryButton { text: qsTr("Save"); enabled: ed._ready; onClicked: ed._save() }
        }
    }

    AppPicker {
        id: appPicker
        onPicked: (app) => {
            ed.value = app.command
            ed.label = app.name
            ed.icon = Backend.cacheAppIcon(app.id) || "application-x-executable-symbolic"
        }
    }
}
