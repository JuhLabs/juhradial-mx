import QtQuick

// Tiny mono keycap for shortcut hints ("Ctrl K", "Esc").
Rectangle {
    property string text: ""
    implicitWidth: kt.implicitWidth + 12
    implicitHeight: 20
    radius: 5
    color: "#14FFFFFF"
    border.width: 1; border.color: Theme.border
    Text {
        id: kt
        anchors.centerIn: parent
        text: parent.text; color: Theme.textMuted
        font.family: Theme.fontMono; font.pixelSize: Theme.fsMicro; font.weight: Font.Medium
    }
}
