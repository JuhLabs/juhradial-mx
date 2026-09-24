import QtQuick
import QtQuick.Dialogs

Column {
    id: ed
    property int pageIndex: 0
    property int keyNumber: 1
    property var draft: ({ action: "none", label: "", icon: "", custom: {} })
    spacing: Theme.gapS

    function load() { draft = Backend.keypadKey(pageIndex, keyNumber) }
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
        width: parent.width; wrapMode: Text.WrapAnywhere
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
        Image {
            visible: (ed.draft.plate || "") !== ""
            width: 40; height: 40
            source: (ed.draft.plate || "") !== "" ? "file://" + ed.draft.plate : ""
            sourceSize.width: 80; sourceSize.height: 80
            fillMode: Image.PreserveAspectCrop; smooth: true
        }
        ActionIcon {
            visible: (ed.draft.plate || "") === "" && !(ed.draft.icon || "").startsWith("desktop:")
            iconName: ed.draft.icon || "input-keyboard-symbolic"
            tint: Theme.accent; px: 32
        }
        PrimaryButton { text: qsTr("Glyph"); ghost: true; onClicked: glyphPicker.open() }
        PrimaryButton { text: qsTr("App icon"); ghost: true; onClicked: iconAppPicker.open() }
        PrimaryButton { text: qsTr("Picture"); ghost: true; onClicked: pictureDialog.open() }
        PrimaryButton {
            visible: (ed.draft.plate || "") !== ""
            text: qsTr("Remove picture"); ghost: true
            onClicked: ed.update("plate", "")
        }
    }
    Text {
        width: parent.width; wrapMode: Text.WordWrap
        text: qsTr("A picture fills the whole key, label included. Otherwise the glyph or app icon sits above the label; long labels are shortened.")
        color: Theme.textMuted; font.family: Theme.fontUI; font.pixelSize: Theme.fsSmall
    }
    PrimaryButton {
        text: qsTr("Save key")
        onClicked: {
            if (Backend.saveKeypadKey(ed.pageIndex, ed.keyNumber, ed.draft))
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
    ActionPicker {
        id: glyphPicker
        title: qsTr("Choose a glyph")
        actions: Backend.keypadGlyphs()
        currentId: ed.draft.icon
        onPicked: (id) => { ed.update("icon", id); ed.update("plate", "") }
    }
    AppPicker {
        id: iconAppPicker
        onPicked: (app) => {
            ed.update("icon", Backend.cacheAppIcon(app.id) || "application-x-executable-symbolic")
            ed.update("plate", "")
        }
    }
    FileDialog {
        id: pictureDialog
        title: qsTr("Choose a picture for this key")
        nameFilters: [qsTr("Images (*.png *.jpg *.jpeg *.webp *.bmp *.svg)")]
        onAccepted: {
            var path = Backend.importKeypadImage(selectedFile.toString())
            if (path !== "") ed.update("plate", path)
        }
    }
    CustomActionEditor {
        id: customEditor
        readAction: function(scope, slot) { return ed.draft.custom || {} }
        writeAction: function(scope, slot, action) {
            ed.update("custom", action)
            if (action.label) ed.update("label", action.label)
            if (action.icon) ed.update("icon", action.icon)
            return true
        }
    }
}
