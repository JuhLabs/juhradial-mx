import QtQuick

// Shadow.qml on Qt older than 6.9, which has no RectangularShadow: a few
// stacked rounded rectangles whose alpha builds up towards the middle. The
// properties match, so the callers are the same on every Qt.
Item {
    id: s
    property real radius: 0
    property real blur: 0
    property real spread: 0
    property color color: "#000000"
    property vector2d offset: Qt.vector2d(0, 0)

    readonly property int _layers: 4
    Repeater {
        model: s._layers
        Rectangle {
            required property int index
            // From half a blur inside the edge to half a blur outside it.
            readonly property real grow: s.spread + s.blur * ((index + 1) / s._layers - 0.5)
            x: s.offset.x - grow; y: s.offset.y - grow
            width: s.width + 2 * grow; height: s.height + 2 * grow
            radius: Math.max(0, s.radius + grow)
            // Each layer carries the alpha that makes all of them add up to color.a.
            color: Qt.rgba(s.color.r, s.color.g, s.color.b, 1 - Math.pow(1 - s.color.a, 1 / s._layers))
        }
    }
}
