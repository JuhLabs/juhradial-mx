import QtQuick

Item {
    id: t
    property bool checked: false
    signal toggled(bool v)
    width: 48; height: 28
    opacity: enabled ? 1.0 : 0.4
    activeFocusOnTab: true
    Keys.onSpacePressed: t._flip()
    Keys.onReturnPressed: t._flip()
    function _flip() { checked = !checked; toggled(checked) }

    Rectangle {
        anchors.fill: parent; radius: height / 2
        color: t.checked ? (ma.containsMouse ? Qt.lighter(Theme.accent, 1.15) : Theme.accent)
                         : (ma.containsMouse ? "#3EFFFFFF" : "#30FFFFFF")
        Behavior on color { ColorAnimation { duration: 160 } }
    }
    Rectangle {   // focus ring
        anchors.fill: parent; anchors.margins: -3
        radius: height / 2; color: "transparent"
        border.color: Theme.accent; border.width: 2
        visible: t.activeFocus
    }
    Rectangle {
        width: ma.pressed ? 24 : 22; height: width; radius: width / 2; color: "white"
        y: (t.height - height) / 2
        x: t.checked ? parent.width - width - 3 : 3
        Behavior on width { NumberAnimation { duration: 90 } }
        Behavior on x { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    }
    MouseArea {
        id: ma
        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
        onClicked: t._flip()
    }
}
