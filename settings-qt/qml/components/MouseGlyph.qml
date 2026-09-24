import QtQuick

// A mouse seen from above, drawn in lines, with one part lit so a card says
// which part it sets: "sensor" (the body: pointer speed), "wheel" (the main
// wheel) or "thumb" (the side wheel under the thumb).
Canvas {
    id: g
    property string part: "sensor"
    property color line: Theme.textMuted
    property color lit: Theme.accent
    width: 22; height: 22

    Accessible.ignored: true

    onPaint: {
        var c = getContext("2d"); c.reset()
        var w = width, h = height
        var lw = Math.max(1.2, Math.min(w, h) / 15)
        c.lineCap = "round"; c.lineJoin = "round"

        function stroke(on) {
            c.strokeStyle = on ? g.lit : g.line
            c.lineWidth = on ? lw * 1.35 : lw
            c.stroke()
        }
        // body: narrow nose, wide palm
        c.beginPath()
        c.moveTo(w * 0.5, h * 0.05)
        c.bezierCurveTo(w * 0.8, h * 0.05, w * 0.86, h * 0.38, w * 0.84, h * 0.62)
        c.bezierCurveTo(w * 0.82, h * 0.9, w * 0.66, h * 0.96, w * 0.5, h * 0.96)
        c.bezierCurveTo(w * 0.34, h * 0.96, w * 0.2, h * 0.9, w * 0.2, h * 0.62)
        c.bezierCurveTo(w * 0.2, h * 0.38, w * 0.22, h * 0.05, w * 0.5, h * 0.05)
        stroke(g.part === "sensor")
        // the split between the two buttons, above and below the wheel
        c.beginPath()
        c.moveTo(w * 0.5, h * 0.05); c.lineTo(w * 0.5, h * 0.15)
        c.moveTo(w * 0.5, h * 0.37); c.lineTo(w * 0.5, h * 0.44)
        stroke(false)
        // main wheel
        c.beginPath()
        c.roundedRect(w * 0.43, h * 0.16, w * 0.14, h * 0.2, w * 0.07, w * 0.07)
        stroke(g.part === "wheel")
        // thumb wheel, sticking out of the left flank
        c.beginPath()
        c.roundedRect(w * 0.04, h * 0.48, w * 0.2, h * 0.09, h * 0.045, h * 0.045)
        stroke(g.part === "thumb")
        // sensor dot
        if (g.part === "sensor") {
            c.beginPath()
            c.arc(w * 0.52, h * 0.7, Math.max(1.2, w * 0.05), 0, 2 * Math.PI)
            c.fillStyle = g.lit
            c.fill()
        }
    }
    onPartChanged: requestPaint()
    onLineChanged: requestPaint()
    onLitChanged: requestPaint()
    onWidthChanged: requestPaint()
    Component.onCompleted: requestPaint()
}
