import QtQuick
import QtQuick.Controls.Basic as B

// Ghost circular icon button (line icon via the image://icon provider).
Item {
    id: ib
    property string icon: ""        // icon name, e.g. "list-add-symbolic"
    property color tint: Theme.textBody
    property real diameter: 34
    // What the button does: shown as a tooltip and read by screen readers.
    property string tip: ""
    signal clicked
    implicitWidth: diameter; implicitHeight: diameter
    opacity: enabled ? 1.0 : 0.4

    activeFocusOnTab: true
    Keys.onSpacePressed: ib.clicked()
    Keys.onReturnPressed: ib.clicked()
    Keys.onEnterPressed: ib.clicked()

    Accessible.role: Accessible.Button
    Accessible.name: tip
    Accessible.onPressAction: ib.clicked()
    B.ToolTip.visible: tip !== "" && (ma.containsMouse || ib.activeFocus)
    B.ToolTip.text: tip
    B.ToolTip.delay: 600

    Rectangle {
        anchors.fill: parent; radius: width / 2
        color: ma.pressed ? "#28FFFFFF" : (ma.containsMouse ? "#18FFFFFF" : "transparent")
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
    }
    FocusHalo { active: ib.activeFocus; radius: ib.diameter / 2; margin: 2 }
    Image {
        anchors.centerIn: parent
        source: ib.icon !== "" ? "image://icon/" + (ib.tint.toString().slice(1)) + "/" + Theme.iconStyle + "/" + ib.icon : ""
        sourceSize.width: Math.round(ib.diameter * 1.2); sourceSize.height: Math.round(ib.diameter * 1.2)
        width: Math.round(ib.diameter * 0.56); height: width; smooth: true
    }
    MouseArea {
        id: ma; anchors.fill: parent; hoverEnabled: true
        cursorShape: Qt.PointingHandCursor; onClicked: ib.clicked()
    }
}
