import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Templates as T
import ".."

// FilePicker.qml where QtQuick.Dialogs is not installed: a sheet that takes
// the path as text, so import and export keep working. Same properties and
// signal as the system dialog.
B.Popup {
    id: picker
    property string title: ""
    property bool saving: false
    property string defaultSuffix: ""
    property url currentFolder: Backend.documentsFolder
    property var nameFilters: []
    property url selectedFile
    signal accepted()

    function _path(url) {
        const s = url.toString()
        return s.startsWith("file://") ? decodeURIComponent(s.slice(7)) : s
    }
    function _accept() {
        var path = field.text.trim()
        if (path === "" || path.endsWith("/")) return
        if (saving && defaultSuffix !== "" && path.split("/").pop().indexOf(".") < 0) path += "." + defaultSuffix
        selectedFile = "file://" + path.split("/").map(encodeURIComponent).join("/")
        close()
        accepted()
    }

    parent: T.Overlay.overlay
    anchors.centerIn: parent
    width: 520
    padding: Theme.pad
    modal: true; dim: true
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside
    onAboutToShow: {
        const start = selectedFile.toString() !== "" ? selectedFile : currentFolder
        field.text = _path(start) + (selectedFile.toString() !== "" || start.toString() === "" ? "" : "/")
        field.field.forceActiveFocus()
    }
    background: Rectangle {
        color: Theme.surfaceGlassHi; radius: Theme.radiusCard
        border.width: 1; border.color: Theme.borderStrong
    }
    contentItem: Column {
        spacing: Theme.gapL
        Text {
            width: parent.width; wrapMode: Text.WordWrap
            text: picker.title !== "" ? picker.title : (picker.saving ? qsTr("Save file") : qsTr("Open file"))
            color: Theme.textPrimary
            font.family: Theme.fontUI; font.pixelSize: Theme.fsH3; font.weight: Font.DemiBold
        }
        Text {
            width: parent.width; wrapMode: Text.WordWrap
            text: qsTr("The system file dialog is not installed, so type the full path of the file.")
            color: Theme.textMuted
            font.family: Theme.fontUI; font.pixelSize: Theme.fsBody
        }
        InputField {
            id: field
            width: parent.width
            mono: true
            accessibleName: qsTr("File path")
            onAccepted: picker._accept()
        }
        Row {
            anchors.right: parent.right
            spacing: Theme.gapS
            PrimaryButton { text: qsTr("Cancel"); ghost: true; onClicked: picker.close() }
            PrimaryButton { text: picker.saving ? qsTr("Save") : qsTr("Open"); onClicked: picker._accept() }
        }
    }
}
