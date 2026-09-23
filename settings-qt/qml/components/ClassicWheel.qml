import QtQuick

// Preview of the classic (0.4.4) radial wheel: the overlay's own vector ring
// with eight slices, drawn here for the picker and page previews. Selecting it
// writes radial.wheel = "none", which is the overlay's built-in fallback.
Canvas {
    id: cw
    property real size: 72
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
            c.fillStyle = i === 0 ? "#2A303C" : "#1B1F28"
            c.fill()
            c.lineWidth = Math.max(1, width / 72)
            c.strokeStyle = "rgba(255,255,255,0.14)"
            c.stroke()
        }
        c.beginPath(); c.arc(cx, cy, ro, 0, 2 * Math.PI)
        c.lineWidth = Math.max(1.5, width / 48); c.strokeStyle = "rgba(255,255,255,0.22)"; c.stroke()
    }
    onWidthChanged: requestPaint()
    Component.onCompleted: requestPaint()
}
