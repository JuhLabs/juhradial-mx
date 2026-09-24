import QtQuick

// A haptic pattern drawn as its beats: one bar per pulse, its height the
// strength (a sketch, from Backend.hapticPatterns()). play() sweeps the
// bars in the accent once, so a Test press shows what just played.
Canvas {
    id: g
    property var beats: []
    property color color: Theme.textMuted
    property color lit: Theme.accent
    property real sweep: -1   // 0..1 while playing, -1 at rest
    width: 34; height: 16

    Accessible.ignored: true

    function play() {
        if (Theme.reduceMotion) return
        sweepAnim.restart()
    }
    NumberAnimation {
        id: sweepAnim
        target: g; property: "sweep"; from: 0; to: 1.05
        duration: 420; easing.type: Easing.Linear
        onFinished: g.sweep = -1
    }

    onPaint: {
        var c = getContext("2d"); c.reset()
        var n = Math.max(1, g.beats.length)
        var slot = width / n, bw = Math.max(2, Math.min(5, slot * 0.55))
        for (var i = 0; i < g.beats.length; i++) {
            var v = g.beats[i]
            var x = i * slot + (slot - bw) / 2
            if (v <= 0) {
                c.fillStyle = g.color
                c.globalAlpha = 0.35
                c.fillRect(x, height / 2 - 0.5, bw, 1)
                c.globalAlpha = 1
                continue
            }
            var h = Math.max(2, v * height)
            c.fillStyle = (g.sweep >= 0 && i / n <= g.sweep) ? g.lit : g.color
            c.beginPath()
            c.roundedRect(x, (height - h) / 2, bw, h, bw / 2, bw / 2)
            c.fill()
        }
    }
    onBeatsChanged: requestPaint()
    onSweepChanged: requestPaint()
    onColorChanged: requestPaint()
    Component.onCompleted: requestPaint()
}
