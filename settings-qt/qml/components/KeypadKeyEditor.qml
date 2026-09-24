import QtQuick
import QtQuick.Dialogs

Column {
    id: ed
    property int pageIndex: 0
    property int keyNumber: 1
    property var draft: ({ action: "none", label: "", icon: "", custom: {} })
    spacing: Theme.gapS

    // The saved key as last loaded: a config change elsewhere (a header
    // switch, the keypad colour) must not throw away unsaved edits.
    property string _saved: ""
    // A two-state key: `key` holds both states, `draft` is the one edited now.
    property var key: ({})
    property int stateIndex: 0
    readonly property bool twoStates: (key.states || []).length > 0
    function _blank() { return { action: "none", label: "", icon: "", custom: {} } }
    function load(keepState) {
        key = Backend.keypadKey(pageIndex, keyNumber); _saved = JSON.stringify(key)
        stateIndex = keepState && (key.states || []).length ? stateIndex : 0
        draft = stateIndex === 0 ? _own(key) : key.states[0]
    }
    function _own(k) { var own = Object.assign({}, k); delete own.states; return own }
    // The whole key with the edited state put back.
    function _full() {
        var states = (key.states || []).slice()
        if (stateIndex === 0) return Object.assign({}, draft, states.length ? { states: states } : {})
        return Object.assign(_own(key), { states: [draft] })
    }
    function showState(i) { key = _full(); stateIndex = i; draft = i === 0 ? _own(key) : key.states[0] }
    function setTwoStates(on) {
        key = _full()
        key = Object.assign(_own(key), on ? { states: [_blank()] } : {})
        showState(on ? 1 : 0)
    }
    function reloadIfChanged() { if (JSON.stringify(Backend.keypadKey(pageIndex, keyNumber)) !== _saved) load(true) }
    function update(field, value) {
        var next = Object.assign({}, draft)
        next[field] = value
        draft = next
    }
    onPageIndexChanged: load()
    onKeyNumberChanged: load()
    Component.onCompleted: load()

    CardHeader {
        width: parent.width
        title: qsTr("Key %1").arg(ed.keyNumber)
        subtitle: qsTr("Choose an action, then make its plate easy to read")
    }
    SettingRow {
        width: parent.width
        label: qsTr("Two states")
        desc: qsTr("Each press runs the state the key shows, then the key turns to the other one")
        Toggle { checked: ed.twoStates; onToggled: (v) => { ed.setTwoStates(v); checked = Qt.binding(() => ed.twoStates) } }
    }
    SegmentedControl {
        visible: ed.twoStates
        width: Math.min(parent.width, 280)
        accessibleName: qsTr("State to edit")
        model: [{ id: "0", name: qsTr("First state") }, { id: "1", name: qsTr("Second state") }]
        currentId: String(ed.stateIndex)
        onActivated: (id) => ed.showState(Number(id))
    }
    Text {
        text: qsTr("Action")
        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
    }
    PrimaryButton {
        width: parent.width
        text: {
            var actions = Backend.buttonActions()
            for (var i = 0; i < actions.length; i++) if (actions[i].id === ed.draft.action) return actions[i].name
            return qsTr("Choose an action")
        }
        ghost: true
        onClicked: actionPicker.open()
    }
    Text {
        visible: ed.draft.action === "custom"
        width: parent.width; wrapMode: Text.WrapAtWordBoundaryOrAnywhere
        text: (ed.draft.custom || {}).value || qsTr("Choose a shortcut, app, command or macro")
        color: Theme.textMuted; font.family: Theme.fontMono; font.pixelSize: Theme.fsSmall
    }
    PrimaryButton {
        visible: ed.draft.action === "custom"
        text: qsTr("Edit custom action"); ghost: true
        onClicked: customEditor.openFor("", "", qsTr("Key %1").arg(ed.keyNumber))
    }
    Text {
        text: qsTr("Label")
        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
    }
    InputField {
        width: parent.width
        accessibleName: qsTr("Key label")
        placeholder: qsTr("Keep it short")
        text: ed.draft.label || ""
        onTextEdited: ed.update("label", text)
    }
    Text {
        text: qsTr("Image")
        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
    }
    Flow {
        width: parent.width
        spacing: Theme.gapS
        // AnimatedImage plays a GIF or animated WebP the way the key will.
        AnimatedImage {
            visible: (ed.draft.plate || "") !== ""
            width: 40; height: 40
            source: (ed.draft.plate || "") !== "" ? "file://" + ed.draft.plate : ""
            fillMode: Image.PreserveAspectCrop; smooth: true
        }
        Image {
            readonly property string art: (ed.draft.plate || "") === "" ? Backend.keypadArtPath(ed.draft.art || "") : ""
            visible: art !== ""
            width: 40; height: 40
            source: art !== "" ? "file://" + art : ""
            sourceSize.width: 80; sourceSize.height: 80
            fillMode: Image.PreserveAspectFit; smooth: true
        }
        ActionIcon {
            visible: (ed.draft.plate || "") === "" && (ed.draft.art || "") === "" && !(ed.draft.icon || "").startsWith("desktop:")
            iconName: ed.draft.icon || "input-keyboard-symbolic"
            tint: Theme.accent; px: 32
        }
        PrimaryButton { text: qsTr("Art"); ghost: true; onClicked: artPicker.open() }
        PrimaryButton { text: qsTr("Glyph"); ghost: true; onClicked: glyphPicker.open() }
        PrimaryButton { text: qsTr("App icon"); ghost: true; onClicked: iconAppPicker.open() }
        PrimaryButton { text: qsTr("Picture"); ghost: true; onClicked: pictureDialog.open() }
        PrimaryButton {
            visible: (ed.draft.plate || "") !== ""
            text: qsTr("Remove picture"); ghost: true
            onClicked: ed.update("plate", "")
        }
    }
    // Per-key style: the plate's colour and whether the label shows.
    readonly property var _style: ed.draft.style || {}
    function _setStyle(field, value) {
        var next = Object.assign({}, ed._style)
        if (value === "" || value === false) delete next[field]; else next[field] = value
        ed.update("style", next)
    }
    Text {
        text: qsTr("Colour")
        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
    }
    Row {
        spacing: 6
        Accessible.role: Accessible.Grouping
        Accessible.name: qsTr("Key colour")
        Repeater {
            model: [{ id: "", name: qsTr("Default"), c: "#070b14" }, { id: "#1d2026", name: qsTr("Graphite"), c: "#1d2026" },
                    { id: "#0d2a4a", name: qsTr("Blue"), c: "#0d2a4a" }, { id: "#0b3a3a", name: qsTr("Teal"), c: "#0b3a3a" },
                    { id: "#11331f", name: qsTr("Green"), c: "#11331f" }, { id: "#3d1016", name: qsTr("Red"), c: "#3d1016" },
                    { id: "#26163f", name: qsTr("Purple"), c: "#26163f" }]
            Rectangle {
                id: sw
                required property var modelData
                readonly property bool picked: (ed._style.background || "") === modelData.id
                width: 26; height: 26; radius: 7
                color: modelData.c
                border.width: picked ? 2 : 1
                border.color: picked ? Theme.accent : (swMa.containsMouse ? "#AAFFFFFF" : Theme.border)
                activeFocusOnTab: true
                Accessible.role: Accessible.RadioButton
                Accessible.name: modelData.name
                Accessible.checked: picked
                Keys.onSpacePressed: ed._setStyle("background", modelData.id)
                Keys.onReturnPressed: ed._setStyle("background", modelData.id)
                FocusHalo { active: sw.activeFocus; radius: 7 }
                MouseArea {
                    id: swMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: ed._setStyle("background", sw.modelData.id)
                }
            }
        }
    }
    SettingRow {
        width: parent.width
        label: qsTr("Show label")
        Toggle { checked: !ed._style.hide_label; onToggled: (v) => { ed._setStyle("hide_label", !v); checked = Qt.binding(() => !ed._style.hide_label) } }
    }
    Text {
        width: parent.width; wrapMode: Text.WordWrap
        text: qsTr("A picture fills the whole key, label included; an animated GIF plays on the key. Art keeps your label on the key; a glyph or app icon sits above it. Long labels are shortened.")
        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
    }
    PrimaryButton {
        text: qsTr("Save key")
        onClicked: {
            if (Backend.saveKeypadKey(ed.pageIndex, ed.keyNumber, ed._full()))
                Backend.notify(qsTr("Key saved"), "info")
        }
    }

    ActionPicker {
        id: actionPicker
        actions: Backend.buttonActions()
        currentId: ed.draft.action
        onPicked: (id) => {
            var rows = Backend.buttonActions()
            var row = rows.filter(function(a) { return a.id === id })[0]
            ed.update("action", id)
            if (id === "custom") customEditor.openFor("", "", qsTr("Key %1").arg(ed.keyNumber))
            else if (row) { ed.update("label", row.name); ed.update("icon", row.icon) }
        }
    }
    KeypadArtPicker {
        id: artPicker
        currentId: ed.draft.art || ""
        onPicked: (id) => { ed.update("art", id); ed.update("plate", "") }
    }
    ActionPicker {
        id: glyphPicker
        title: qsTr("Choose a glyph")
        actions: Backend.keypadGlyphs()
        currentId: ed.draft.icon
        onPicked: (id) => { ed.update("icon", id); ed.update("plate", ""); ed.update("art", "") }
    }
    AppPicker {
        id: iconAppPicker
        onPicked: (app) => {
            ed.update("icon", Backend.cacheAppIcon(app.id) || "application-x-executable-symbolic")
            ed.update("plate", ""); ed.update("art", "")
        }
    }
    FileDialog {
        id: pictureDialog
        title: qsTr("Choose a picture for this key")
        nameFilters: [qsTr("Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.svg)")]
        onAccepted: {
            var path = Backend.importKeypadImage(selectedFile.toString())
            if (path !== "") { ed.update("plate", path); ed.update("art", "") }
        }
    }
    CustomActionEditor {
        id: customEditor
        keypadPages: (Backend.keypadRevision, Backend.keypadPages.map(function (p) { return p.name }))
        readAction: function(scope, slot) { return ed.draft.custom || {} }
        writeAction: function(scope, slot, action) {
            ed.update("custom", action)
            if (action.label) ed.update("label", action.label)
            if (action.icon) ed.update("icon", action.icon)
            return true
        }
    }
}
