import QtQuick

// Accent-filled (default) or ghost button. Emits clicked().
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

    readonly property color _base: danger ? Theme.danger : Theme.accent

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusCtl
        color: btn.ghost ? ((ma.containsMouse && btn.enabled) ? "#1CFFFFFF" : "transparent")
                         : ((ma.pressed && btn.enabled) ? Qt.darker(btn._base, 1.12)
                            : ((ma.containsMouse && btn.enabled) ? Qt.lighter(btn._base, 1.08) : btn._base))
        border.width: btn.ghost ? 1 : 0
        border.color: Theme.borderStrong
        Behavior on color { ColorAnimation { duration: Theme.dShort } }
        scale: ma.pressed && btn.enabled ? 0.97 : 1.0
        Behavior on scale { NumberAnimation { duration: Theme.dShort; easing.type: Easing.OutCubic } }
    }
    Rectangle {   // focus ring
        anchors.fill: parent; anchors.margins: -3
        radius: Theme.radiusCtl + 3; color: "transparent"
        border.color: Theme.accent; border.width: 1
        visible: btn.activeFocus
    }
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
