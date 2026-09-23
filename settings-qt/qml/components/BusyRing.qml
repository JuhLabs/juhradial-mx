import QtQuick
import QtQuick.Shapes

// Smooth GPU-driven loader: an azure arc that rotates continuously.
// Replaces the old per-frame timer spinner; declarative, self-stopping when hidden.
Item {
    id: ring
    property real size: 56
    property color color: Theme.accent
    width: size; height: size

    Shape {
        anchors.fill: parent
        antialiasing: true
        ShapePath {
            strokeColor: ring.color
            strokeWidth: Math.max(3, ring.size * 0.08)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: ring.width / 2; centerY: ring.height / 2
                radiusX: ring.width / 2 - ring.strokeInset
                radiusY: ring.height / 2 - ring.strokeInset
                startAngle: 0; sweepAngle: 290
            }
        }
    }
    property real strokeInset: Math.max(4, size * 0.09)

    RotationAnimator on rotation {
        from: 0; to: 360
        duration: 1000
        loops: Animation.Infinite
        running: ring.visible
    }
}
