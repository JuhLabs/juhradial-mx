import QtQuick

// Continuous slider. `value` is real in [from,to]. Emits moved() live while
// dragging and committed() once on release (throttle D-Bus / hardware writes).
Item {
    id: s
    property real from: 0
    property real to: 1
    property real value: 0.5
    property bool showValue: false
    property string suffix: ""
    signal moved(real v)
    signal committed(real v)

    width: 220; height: 24
    readonly property real _frac: (to > from) ? (value - from) / (to - from) : 0

    activeFocusOnTab: true
    Keys.onLeftPressed: _nudge(-1)
    Keys.onRightPressed: _nudge(1)
    function _nudge(dir) {
        var st = Math.max((to - from) / 20, 1)
        value = Math.max(from, Math.min(to, value + dir * st))
        moved(value); committed(value)
    }

    Rectangle {   // focus ring
        anchors.fill: parent; anchors.margins: -4
        radius: Theme.radiusCtl; color: "transparent"
        border.color: Theme.accent; border.width: 1
        visible: s.activeFocus
    }
    Rectangle {
        id: track
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        width: s.showValue ? parent.width - valLbl.width - 12 : parent.width
        height: 5; radius: 3; color: "#26FFFFFF"
    }
    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: track.left
        height: 5; radius: 3; width: track.width * s._frac
        color: Theme.accent
        Behavior on width { enabled: !ma.pressed; NumberAnimation { duration: 90 } }
    }
    Rectangle {
        id: knob
        width: ma.pressed ? 20 : 17; height: width; radius: width / 2
        color: "white"; border.color: Theme.accent; border.width: 2
        anchors.verticalCenter: parent.verticalCenter
        x: track.x + (track.width - width) * s._frac
        Behavior on width { NumberAnimation { duration: 90 } }
        Behavior on x { enabled: !ma.pressed; NumberAnimation { duration: 90 } }
    }
    Text {
        id: valLbl
        visible: s.showValue
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: Math.round(s.value) + s.suffix
        color: Theme.textBody; font.family: Theme.fontUI
        font.pixelSize: Theme.fsSmall; font.weight: Font.Medium
        width: visible ? Math.max(34, implicitWidth) : 0
        horizontalAlignment: Text.AlignRight
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        function setAt(mx) {
            var f = Math.max(0, Math.min(1, (mx - track.x) / track.width))
            s.value = s.from + f * (s.to - s.from)
            s.moved(s.value)
        }
        onPressed: (m) => setAt(m.x)
        onPositionChanged: (m) => { if (pressed) setAt(m.x) }
        onReleased: s.committed(s.value)
    }
}
