import QtQuick
import QtQuick.Effects

// Switch. Checked = accent fill + a soft glow (it is "on", so it is lit).
Item {
    id: t
    property bool checked: false
    signal toggled(bool v)
    width: 46; height: 26
    opacity: enabled ? 1.0 : 0.4
    activeFocusOnTab: true
    Keys.onSpacePressed: t._flip()
    Keys.onReturnPressed: t._flip()
    function _flip() { checked = !checked; toggled(checked) }

    RectangularShadow {
        anchors.fill: parent
        radius: height / 2
        blur: 12; spread: 0
        color: Theme.accentGlow
        opacity: t.checked ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.dMed } }
    }
    Rectangle {
        anchors.fill: parent; radius: height / 2
        color: t.checked ? (ma.containsMouse ? Theme.accentHover : Theme.accent)
                         : (ma.containsMouse ? "#3AFFFFFF" : "#2AFFFFFF")
        border.width: 1
        border.color: t.checked ? "transparent" : Theme.border
        Behavior on color { ColorAnimation { duration: 160 } }
    }
    FocusHalo { active: t.activeFocus; radius: t.height / 2 }
    Rectangle {
        width: ma.pressed ? 22 : 20; height: 20; radius: 10; color: "white"
        y: 3
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
