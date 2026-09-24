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

    property string kind: "shortcut"   // shortcut | app | command | url | macro | plugin | text
    property bool hold: false           // shortcut: keys stay down while the button is held
    property bool pressEnter: false     // text: press Enter after pasting
    property string pasteWith: "auto"   // text: "auto" (by app), "" (Ctrl+V) or "ctrl+shift+v"
    property string value: ""
    property string label: ""
    property string icon: ""
    property var _macros: []
    property var _plugins: []
    // Optional adapters let keypad keys reuse the same editor and pickers.
    property var readAction: null
    property var writeAction: null

    modal: true; dim: true; focus: true
    width: 500
    height: Math.min(implicitHeight, parent ? parent.height - 60 : 560)
    anchors.centerIn: B.Overlay.overlay
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside
    padding: 22

    function openFor(scope, slot, name) {
        ed.scope = scope; ed.slot = slot; ed.buttonName = name
        var c = readAction ? readAction(scope, slot) : Backend.customAction(scope, slot)
        ed.value = c.value || ""; ed.label = c.label || ""; ed.icon = c.icon || ""
        ed.hold = !!c.hold; ed.pressEnter = !!c.enter; ed.pasteWith = c.kind === "text" ? (c.paste_with || "") : "auto"
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
        var action = {
            kind: kind === "app" ? "command" : kind,
            value: value.trim(),
            label: (kind === "app" || kind === "macro" || kind === "plugin") ? label : "",
            icon: kind === "app" ? icon : ""
        }
        if (kind === "text") {
            action.value = value   // pasted as typed, spaces included
            action.enter = pressEnter
            if (pasteWith !== "") action.paste_with = pasteWith
        }
        if (kind === "shortcut" && hold) action.hold = true
        var ok = writeAction ? writeAction(scope, slot, action) : Backend.setCustomAction(scope, slot, action)
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
                    { id: "macro", name: qsTr("Macro") }, { id: "plugin", name: qsTr("Plugin") },
                    { id: "text", name: qsTr("Text") }]
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

        // ---- text ----
        InputField {
            visible: ed.kind === "text"
            width: parent.width
            accessibleName: qsTr("Text to paste")
            placeholder: qsTr("Text, a prompt or a /command")
            text: ed.kind === "text" ? ed.value : ""
            onTextEdited: ed.value = text
        }
        SettingRow {
            visible: ed.kind === "text"
            width: parent.width
            label: qsTr("Press Enter after")
            desc: qsTr("Sends it right away, like a chat message or a command")
            Toggle { checked: ed.pressEnter; accessibleName: qsTr("Press Enter after"); onToggled: (v) => ed.pressEnter = v }
        }
        SegmentedControl {
            visible: ed.kind === "text"
            width: parent.width
            accessibleName: qsTr("Paste with")
            model: [{ id: "auto", name: qsTr("Automatic") }, { id: "", name: qsTr("Ctrl+V") },
                    { id: "ctrl+shift+v", name: qsTr("Ctrl+Shift+V") }]
            currentId: ed.pasteWith
            onActivated: (id) => ed.pasteWith = id
        }
        Text {
            width: parent.width; wrapMode: Text.WordWrap
            visible: ed.kind === "text"
            text: qsTr("Pasted through the clipboard, so every keyboard layout gets the exact characters. Automatic uses Ctrl+Shift+V in terminals and Ctrl+V everywhere else.")
            color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro
        }
        SettingRow {
            visible: ed.kind === "shortcut"
            width: parent.width
            label: qsTr("Hold while pressed")
            desc: qsTr("The keys stay down as long as you hold the button (push to talk)")
            Toggle { checked: ed.hold; accessibleName: qsTr("Hold while pressed"); onToggled: (v) => ed.hold = v }
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
