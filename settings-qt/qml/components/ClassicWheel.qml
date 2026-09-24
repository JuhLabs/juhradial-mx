import QtQuick

// Preview of the classic (0.4.4) radial wheel: the overlay's own vector ring
// with eight slices, drawn here for the picker and page previews. Selecting it
// writes radial.wheel = "none", which is the overlay's built-in fallback.
Canvas {
    id: cw
    property real size: 72
    // The ring palette's surface (Themes > Ring colours): overlay "base" / "surface2".
    property color fill: "#1B1F28"
    property color hi: "#2A303C"
    property color stroke: "#38FFFFFF"
    width: size; height: size
    onPaint: {
        var c = getContext("2d"); c.reset()
        var cx = width / 2, cy = height / 2
        var ro = width * 0.48, ri = width * 0.20
        for (var i = 0; i < 8; i++) {
            var a0 = (i * 45 - 90 - 22.5) * Math.PI / 180, a1 = a0 + 45 * Math.PI / 180
            c.beginPath()
            c.arc(cx, cy, ro, a0, a1, false)
            c.arc(cx, cy, ri, a1, a0, true)
            c.closePath()
            c.fillStyle = i === 0 ? cw.hi : cw.fill
            c.fill()
            c.lineWidth = Math.max(1, width / 72)
            c.strokeStyle = Qt.rgba(cw.stroke.r, cw.stroke.g, cw.stroke.b, cw.stroke.a * 0.64)
            c.stroke()
        }
        c.beginPath(); c.arc(cx, cy, ro, 0, 2 * Math.PI)
        c.lineWidth = Math.max(1.5, width / 48); c.strokeStyle = cw.stroke; c.stroke()
    }
    onWidthChanged: requestPaint()
    onFillChanged: requestPaint()
    onHiChanged: requestPaint()
    onStrokeChanged: requestPaint()
    Component.onCompleted: requestPaint()
}
