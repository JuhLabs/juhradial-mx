import QtQuick.Dialogs

// The system file dialog. `saving` asks for a file to write instead of one to
// open, so callers need nothing from QtQuick.Dialogs themselves. Where that
// module is not installed, +nodialogs/FilePicker.qml asks for the path.
FileDialog {
    property bool saving: false
    fileMode: saving ? FileDialog.SaveFile : FileDialog.OpenFile
}
