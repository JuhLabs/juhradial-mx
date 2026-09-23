import QtQuick

// Continuous slider. `value` is real in [from,to]. Emits moved() live while
// dragging and committed() once on release (throttle D-Bus / hardware writes).
// The readout is mono: "mono means numbers".
Item {
    id: s
    property real from: 0
    property real to: 1
    property real value: 0.5
    property bool showValue: false
    property string suffix: ""
    // Keyboard steps: 0 = automatic ((to - from) / 20 and / 10).
    property real stepSize: 0
    property real pageStep: 0
    property string accessibleName: ""
    property string accessibleDescription: ""
    signal moved(real v)
    signal committed(real v)

    width: 220; height: 26
    readonly property real _frac: (to > from) ? (value - from) / (to - from) : 0

    activeFocusOnTab: true
    Keys.onLeftPressed: _nudge(-1)
    Keys.onDownPressed: _nudge(-1)
    Keys.onRightPressed: _nudge(1)
    Keys.onUpPressed: _nudge(1)
    Keys.onPressed: (e) => {
        if (e.key === Qt.Key_PageUp) { _nudge(1, true); e.accepted = true }
        else if (e.key === Qt.Key_PageDown) { _nudge(-1, true); e.accepted = true }
        else if (e.key === Qt.Key_Home) { _setKey(from); e.accepted = true }
        else if (e.key === Qt.Key_End) { _setKey(to); e.accepted = true }
    }
    function _nudge(dir, page) {
        var st = page ? (pageStep > 0 ? pageStep : Math.max((to - from) / 10, 1))
                      : (stepSize > 0 ? stepSize : Math.max((to - from) / 20, 1))
        var v = value + dir * st
        if (stepSize > 0) v = from + Math.round((v - from) / stepSize) * stepSize
        _setKey(v)
    }
    function _setKey(v) {
        value = Math.max(from, Math.min(to, v))
        moved(value); committed(value)
    }

    Accessible.role: Accessible.Slider
    Accessible.name: accessibleName
    Accessible.description: accessibleDescription
    Accessible.onIncreaseAction: _nudge(1)
    Accessible.onDecreaseAction: _nudge(-1)

    Rectangle {
        id: track
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        width: s.showValue ? parent.width - valLbl.width - 14 : parent.width
        height: 6; radius: 3; color: "#26FFFFFF"
        border.width: 1; border.color: "#0AFFFFFF"
    }
    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: track.left
        height: 6; radius: 3; width: Math.max(6, track.width * s._frac)
        color: Theme.accent
        Behavior on width { enabled: !ma.pressed; NumberAnimation { duration: 90 } }
    }
    Rectangle {
        id: knob
        width: ma.pressed ? 20 : 18; height: width; radius: width / 2
        color: "white"; border.color: Theme.accent; border.width: 2
        anchors.verticalCenter: parent.verticalCenter
        x: track.x + (track.width - width) * s._frac
        Behavior on width { NumberAnimation { duration: 90 } }
        Behavior on x { enabled: !ma.pressed; NumberAnimation { duration: 90 } }
        FocusHalo { active: s.activeFocus; radius: knob.width / 2; margin: 3 }
    }
    Text {
        id: valLbl
        visible: s.showValue
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: Math.round(s.value) + s.suffix
        color: Theme.textBody; font.family: Theme.fontMono
        font.pixelSize: Theme.fsSmall; font.weight: Font.Medium
        width: visible ? Math.max(38, implicitWidth) : 0
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
