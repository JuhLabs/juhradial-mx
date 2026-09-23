import QtQuick

// Small status pill. Set `accent` true for the themed accent style, or pass a
// custom `tint` colour. `dot` shows a leading status dot.
Item {
    id: b
    property string text: ""
    property bool accent: false
    property bool dot: false
    property color tint: accent ? Theme.accent : Theme.textMuted
    implicitWidth: row.width + 20
    implicitHeight: 24

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Qt.rgba(b.tint.r, b.tint.g, b.tint.b, 0.14)
        border.width: 1
        border.color: Qt.rgba(b.tint.r, b.tint.g, b.tint.b, 0.45)
    }
    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        Rectangle {
            visible: b.dot
            width: 7; height: 7; radius: 4; color: b.tint
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: b.text; color: b.tint
            font.family: Theme.fontUI; font.pixelSize: Theme.fsMicro; font.weight: Font.DemiBold
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
