import QtQuick

// Accent-filled (default), ghost or danger button. One filled button per view.
// Hover brightens, press darkens; nothing scales.
Item {
    id: btn
    property string text: ""
    property bool ghost: false
    property bool danger: false
    signal clicked
    implicitWidth: lbl.implicitWidth + 36
    implicitHeight: 38
    opacity: enabled ? 1.0 : 0.45

    activeFocusOnTab: true
    Keys.onSpacePressed: if (btn.enabled) btn.clicked()
    Keys.onReturnPressed: if (btn.enabled) btn.clicked()
    Keys.onEnterPressed: if (btn.enabled) btn.clicked()
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.onPressAction: if (btn.enabled) btn.clicked()

    readonly property color _base: danger ? Theme.danger : Theme.accent

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusCtl
        color: btn.ghost ? ((ma.pressed && btn.enabled) ? "#26FFFFFF"
                            : ((ma.containsMouse && btn.enabled) ? "#1AFFFFFF" : "#0EFFFFFF"))
                         : ((ma.pressed && btn.enabled) ? Qt.darker(btn._base, 1.12)
                            : ((ma.containsMouse && btn.enabled) ? Qt.lighter(btn._base, 1.08) : btn._base))
        border.width: 1
        border.color: btn.ghost ? (ma.containsMouse ? Theme.borderStrong : Theme.border) : "transparent"
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
        Rectangle {   // lit top edge on the filled button
            visible: !btn.ghost
            anchors { left: parent.left; right: parent.right; top: parent.top }
            anchors.margins: 1; height: 1; radius: 1; color: "#33FFFFFF"
        }
    }
    FocusHalo { active: btn.activeFocus; radius: Theme.radiusCtl }
    Text {
        id: lbl
        anchors.centerIn: parent
        text: btn.text
        color: btn.ghost ? Theme.textBody : Theme.bgBase
        font.family: Theme.fontUI; font.pixelSize: Theme.fsBody; font.weight: Font.DemiBold
    }
    MouseArea {
        id: ma; anchors.fill: parent; hoverEnabled: true
        cursorShape: Qt.PointingHandCursor; onClicked: btn.clicked()
    }
}
