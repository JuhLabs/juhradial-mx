import QtQuick
import QtQuick.Shapes
import QtQuick.Effects

// Battery gauge: a glowing ring whose colour is driven by charge level (NOT the
// theme) plus a detailed battery glyph in the centre. Green when healthy, amber
// at 50-60%, red below 50%.
Item {
    id: r
    property int percent: 0
    property bool charging: false
    property real size: 120
    width: size; height: size

    readonly property color lvl: percent < 50 ? "#F4513B"
                                 : percent <= 60 ? "#F5A623" : "#33D17A"

    // faint track
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: "#22FFFFFF"; strokeWidth: Math.max(5, r.size * 0.07)
            fillColor: "transparent"; capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: r.width / 2; centerY: r.height / 2
                radiusX: r.width / 2 - r.size * 0.06; radiusY: r.height / 2 - r.size * 0.06
                startAngle: -90; sweepAngle: 360
            }
        }
    }
    // glowing level arc
    Shape {
        id: arc
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        // render the shape into a multisampled layer so the MultiEffect glow
        // does not upscale a low-res texture (was visibly pixelated at HiDPI).
        layer.enabled: true
        layer.samples: 8
        layer.smooth: true
        layer.textureSize: Qt.size(r.width * 2, r.height * 2)
        layer.effect: MultiEffect {
            shadowEnabled: true; shadowColor: r.lvl
            shadowBlur: 1.0; shadowOpacity: 0.85
            shadowHorizontalOffset: 0; shadowVerticalOffset: 0
        }
        ShapePath {
            strokeColor: r.lvl; strokeWidth: Math.max(5, r.size * 0.07)
            fillColor: "transparent"; capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: r.width / 2; centerY: r.height / 2
                radiusX: r.width / 2 - r.size * 0.06; radiusY: r.height / 2 - r.size * 0.06
                startAngle: -90; sweepAngle: 360 * Math.max(0, Math.min(100, r.percent)) / 100
            }
        }
        Behavior on opacity { NumberAnimation { duration: 220 } }
    }

    // centre: percent + detailed battery glyph
    Column {
        anchors.centerIn: parent
        spacing: r.size * 0.04
        Row {
            anchors.horizontalCenter: parent.horizontalCenter; spacing: 1
            Text {
                text: r.percent; color: Theme.textPrimary
                font.family: Theme.fontUI; font.pixelSize: Math.round(r.size * 0.25); font.weight: Font.DemiBold
            }
            Text {
                text: "%"; color: Theme.textMuted; anchors.bottom: parent.bottom
                anchors.bottomMargin: r.size * 0.045
                font.family: Theme.fontUI; font.pixelSize: Math.round(r.size * 0.12)
            }
        }
        // detailed battery icon
        Item {
            id: glyph
            width: r.size * 0.36; height: r.size * 0.18
            anchors.horizontalCenter: parent.horizontalCenter
            Rectangle {  // body
                id: body
                width: parent.width - nub.width; height: parent.height
                radius: height * 0.28
                color: "transparent"; border.color: r.lvl; border.width: Math.max(1.5, r.size * 0.014)
            }
            Rectangle {  // terminal nub
                id: nub
                anchors.left: body.right; anchors.verticalCenter: body.verticalCenter
                width: r.size * 0.022; height: parent.height * 0.42
                radius: width / 2; color: r.lvl
            }
            Rectangle {  // fill
                x: body.border.width + 1.5
                anchors.verticalCenter: body.verticalCenter
                height: body.height - (body.border.width + 1.5) * 2
                width: Math.max(0, (body.width - (body.border.width + 1.5) * 2) * Math.min(100, r.percent) / 100)
                radius: height * 0.3; color: r.lvl
                Behavior on width { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
            }
            // charging bolt
            Canvas {
                anchors.centerIn: body
                width: parent.height * 0.8; height: parent.height * 0.8
                visible: r.charging
                onPaint: {
                    var c = getContext("2d"); c.reset()
                    c.fillStyle = "#FFFFFF"; c.strokeStyle = "#0A0A0A"; c.lineWidth = 1.2
                    var w = width, h = height
                    c.beginPath()
                    c.moveTo(w * 0.58, 0); c.lineTo(w * 0.18, h * 0.58)
                    c.lineTo(w * 0.48, h * 0.58); c.lineTo(w * 0.42, h)
                    c.lineTo(w * 0.86, h * 0.40); c.lineTo(w * 0.54, h * 0.40)
                    c.closePath(); c.fill(); c.stroke()
                }
            }
        }
        Text {
            visible: r.charging
            text: "Charging"; color: r.lvl
            font.family: Theme.fontUI; font.pixelSize: Math.round(r.size * 0.095); font.weight: Font.Medium
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }
}
