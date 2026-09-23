import QtQuick

// Ghost circular icon button (freedesktop icon via the image://icon provider).
Item {
    id: ib
    property string icon: ""        // freedesktop name, e.g. "list-add-symbolic"
    property color tint: Theme.textBody
    property real diameter: 34
    signal clicked
    implicitWidth: diameter; implicitHeight: diameter

    activeFocusOnTab: true
    Keys.onSpacePressed: ib.clicked()
    Keys.onReturnPressed: ib.clicked()

    Rectangle {
        anchors.fill: parent; radius: width / 2
        color: ma.pressed ? "#28FFFFFF" : (ma.containsMouse ? "#18FFFFFF" : "transparent")
        border.width: ib.activeFocus ? 1 : 0
        border.color: Theme.accent
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
    }
    Image {
        anchors.centerIn: parent
        source: ib.icon !== "" ? "image://icon/" + (ib.tint.toString().slice(1)) + "/" + ib.icon : ""
        sourceSize.width: ib.diameter; sourceSize.height: ib.diameter
        width: ib.diameter * 0.52; height: width; smooth: true
    }
    MouseArea {
        id: ma; anchors.fill: parent; hoverEnabled: true
        cursorShape: Qt.PointingHandCursor; onClicked: ib.clicked()
    }
}
