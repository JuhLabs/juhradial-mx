import QtQuick
import QtQuick.Effects

// Keyboard focus lights up like every other live state: a 2 px accent ring
// with a soft halo. Drop inside any control; anchors to the parent bounds.
Item {
    id: h
    property bool active: false
    property real radius: Theme.radiusCtl
    property real margin: 3
    anchors.fill: parent
    anchors.margins: -margin
    visible: active
    RectangularShadow {
        anchors.fill: parent
        radius: h.radius + h.margin
        blur: 8; spread: 1
        color: Theme.accentSubtle
    }
    Rectangle {
        anchors.fill: parent
        radius: h.radius + h.margin
        color: "transparent"
        border.width: 2; border.color: Theme.accent
    }
}
